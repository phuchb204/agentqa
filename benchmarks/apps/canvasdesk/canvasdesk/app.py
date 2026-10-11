from __future__ import annotations

import html
import json
import secrets
from typing import Annotated, Any

from fastapi import Body, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from canvasdesk.state import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CanvasdeskStore,
    NamespaceError,
    opaque_ref,
)

SESSION_COOKIE = "cd_session"
CONTROL_HEADER = "x-canvasdesk-control"
DELAYED_RENDER_MS = 400
APP_VERSION = 1


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CellSeed(StrictPayload):
    id: str
    name: str
    color: str = "#c0392b"


class PreparePayload(StrictPayload):
    accounts: dict[str, str] = {}
    cells: list[CellSeed] = []


class MutationPayload(StrictPayload):
    operator: str
    params: dict[str, Any] = {}


def _page(title: str, body: str) -> HTMLResponse:
    document = (
        "<!doctype html>\n"
        '<html lang="vi">\n'
        '<head><meta charset="utf-8"><title>' + html.escape(title) + "</title></head>\n"
        f"<body><main><h1>{html.escape(title)}</h1>{body}</main></body>\n</html>\n"
    )
    return HTMLResponse(document)


def _login_page(namespace: str, error: str | None = None) -> HTMLResponse:
    error_html = f'<p class="login-error">{html.escape(error)}</p>' if error else ""
    body = (
        error_html
        + f'<form method="post" action="/{namespace}/login">'
        + '<p><label for="username">Tài khoản</label> '
        + '<input id="username" name="username" type="text" required></p>'
        + '<p><label for="password">Mật khẩu</label> '
        + '<input id="password" name="password" type="password" required></p>'
        + '<button type="submit">Đăng nhập</button>'
        + "</form>"
    )
    return _page("Đăng nhập Canvasdesk", body)


BOARD_SCRIPT = """
<script>
const config = window.__canvasdesk;
const canvas = document.getElementById('board-canvas');
const context = canvas.getContext('2d');
function draw() {
  const theme = document.getElementById('board-stage').getAttribute('data-theme');
  const background = theme === 'dark' ? '#202030' : '#f5f5f5';
  context.fillStyle = background;
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (const cell of config.cells) {
    context.fillStyle = cell.color;
    context.fillRect(cell.x, cell.y, cell.width, cell.height);
    if (cell.id === config.selectedId) {
      context.fillStyle = '#101010';
      context.fillRect(cell.x + 8, cell.y + 8, cell.width - 16, cell.height - 16);
    }
  }
}
draw();
window.__canvasdeskDraw = draw;
</script>
"""

DELAYED_SCRIPT = """
<script>
const delay = window.__canvasdesk.delayMs;
setTimeout(async () => {
  document.getElementById('delayed-widget').hidden = false;
  try {
    await fetch(location.pathname.replace('/board', '/api/rendered'), { method: 'POST' });
  } catch (error) {
    /* beacon lỗi không chặn hiển thị */
  }
}, delay);
</script>
"""


def _render_board(namespace: str, store: CanvasdeskStore) -> str:
    state = store.state(namespace)
    mutation = state.get("mutation") or {}
    mutation_patch = mutation.get("patch") or {}
    config = {
        "cells": [
            {
                "id": cell["id"],
                "x": cell["x"],
                "y": cell["y"],
                "width": cell["width"],
                "height": cell["height"],
                "color": cell["color"],
            }
            for cell in state["cells"]
        ],
        "selectedId": None,
        "delayMs": int(mutation_patch.get("ms", DELAYED_RENDER_MS)),
    }
    for cell in state["cells"]:
        if state["selected_ref"] == opaque_ref(namespace, cell["id"]):
            config["selectedId"] = cell["id"]
    hotspots = []
    for cell in state["cells"]:
        selected = cell["id"] == config["selectedId"]
        hotspots.append(
            f'<form method="post" action="/{namespace}/board/select" style="position:absolute;'
            f'left:{cell["x"]}px;top:{cell["y"]}px;width:{cell["width"]}px;height:{cell["height"]}px;margin:0">'
            f'<input type="hidden" name="cell_id" value="{html.escape(cell["id"], quote=True)}">'
            f'<button class="hotspot" type="submit" aria-label="{html.escape(cell["name"])}" '
            f'data-selected="{"true" if selected else "false"}" '
            f'style="width:100%;height:100%;opacity:0.01"></button></form>'
        )
    if mutation.get("operator") == "duplicate_label" and state["cells"]:
        duplicated = str(mutation_patch.get("duplicated", state["cells"][0]["name"]))
        distractor = next(
            (cell for cell in state["cells"] if cell["id"] == mutation_patch.get("distractor_cell")),
            state["cells"][-1],
        )
        hotspots.append(
            f'<form method="post" action="/{namespace}/board/select" style="position:absolute;'
            f"left:{distractor['x']}px;top:{distractor['y']}px;width:{distractor['width']}px;"
            f'height:{distractor["height"]}px;margin:0">'
            f'<input type="hidden" name="cell_id" value="{html.escape(distractor["id"], quote=True)}">'
            f'<button class="hotspot" type="submit" aria-label="{html.escape(duplicated)}" '
            'data-selected="false" style="width:100%;height:100%;opacity:0.01"></button></form>'
        )
    selected_text = "chưa chọn"
    for cell in state["cells"]:
        if state["selected_ref"] == opaque_ref(namespace, cell["id"]):
            selected_text = cell["name"]
    confirmed = '<p id="layout-status">Bố cục đã xác nhận</p>' if state["layout_confirmed"] else ""
    body = (
        "<style>body{margin:0;font-family:sans-serif}h1{margin:8px;font-size:20px;line-height:28px}"
        "#board-stage{margin:0 8px}</style>"
        f'<div id="board-stage" data-theme="{html.escape(state["theme"])}" '
        f'style="position:relative;width:{CANVAS_WIDTH}px;height:{CANVAS_HEIGHT}px">'
        f'<canvas id="board-canvas" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}"></canvas>'
        + "".join(hotspots)
        + "</div>"
        + f'<p id="selection-status">Đang chọn: {html.escape(selected_text)}</p>'
        + f'<form method="post" action="/{namespace}/board/theme">'
        + '<button type="submit" id="theme-toggle">Đổi nền</button></form>'
        + '<div id="board-scroll" style="height:80px;overflow:auto;width:400px">'
        + '<div style="height:600px"></div>'
        + f'<form method="post" action="/{namespace}/board/confirm">'
        + '<button type="submit" id="reveal-done">Hoàn tất bố cục</button></form></div>'
        + confirmed
        + '<p id="delayed-placeholder">Đang tải tiện ích</p>'
        + '<div id="delayed-widget" hidden>Tiện ích đã sẵn sàng</div>'
        + f"<script>window.__canvasdesk = {json.dumps(config, ensure_ascii=False)};</script>"
        + BOARD_SCRIPT
        + DELAYED_SCRIPT
    )
    return body


def create_canvasdesk_app(control_token: str, store: CanvasdeskStore | None = None) -> FastAPI:
    app = FastAPI(title="Canvasdesk fixture", version=str(APP_VERSION))
    canvasdesk = store if store is not None else CanvasdeskStore()
    sessions: dict[str, tuple[str, str]] = {}
    app.state.canvasdesk = canvasdesk
    app.state.sessions = sessions

    def require_control(token: str | None) -> None:
        if control_token == "" or token != control_token:
            raise HTTPException(status_code=401, detail="control token không hợp lệ")

    def session_namespace(request: Request, namespace: str) -> str | None:
        token = request.cookies.get(SESSION_COOKIE)
        if token is None:
            return None
        session = sessions.get(token)
        if session is None or session[0] != namespace:
            return None
        return session[1]

    def namespace_guard(namespace: str) -> JSONResponse | None:
        if not canvasdesk.exists(namespace):
            return JSONResponse(status_code=404, content={"error": "namespace chưa được prepare"})
        return None

    @app.exception_handler(NamespaceError)
    async def namespace_error_handler(_request: Request, exc: NamespaceError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.get("/{namespace}/login", response_class=HTMLResponse)
    def login_form(namespace: str) -> HTMLResponse:
        return _login_page(namespace)

    @app.post("/{namespace}/login")
    def login_submit(namespace: str, username: Annotated[str, Form()], password: Annotated[str, Form()]) -> Any:
        if not canvasdesk.authenticate(namespace, username, password):
            canvasdesk.record(namespace, "login_failed", detail=username)
            return _login_page(namespace, "Sai tài khoản hoặc mật khẩu")
        token = secrets.token_urlsafe(24)
        sessions[token] = (namespace, username)
        canvasdesk.record(namespace, "login", detail=username)
        response = RedirectResponse(url=f"/{namespace}/board", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return response

    @app.get("/{namespace}/board", response_class=HTMLResponse)
    def board_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Bảng bố cục", _render_board(namespace, canvasdesk))

    @app.post("/{namespace}/board/select")
    def board_select(request: Request, namespace: str, cell_id: Annotated[str, Form()]) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        canvasdesk.select_hotspot(namespace, cell_id)
        return RedirectResponse(url=f"/{namespace}/board", status_code=303)

    @app.post("/{namespace}/board/theme")
    def board_theme(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        canvasdesk.toggle_theme(namespace)
        return RedirectResponse(url=f"/{namespace}/board", status_code=303)

    @app.post("/{namespace}/board/confirm")
    def board_confirm(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        canvasdesk.confirm_layout(namespace)
        return RedirectResponse(url=f"/{namespace}/board", status_code=303)

    @app.post("/{namespace}/api/rendered")
    def api_rendered(request: Request, namespace: str) -> JSONResponse:
        if session_namespace(request, namespace) is None:
            return JSONResponse(status_code=401, content={"error": "chưa đăng nhập"})
        canvasdesk.record_delayed_rendered(namespace)
        return JSONResponse(content={"ok": True})

    @app.get("/_control/version")
    def control_version(x_canvasdesk_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_canvasdesk_control)
        return JSONResponse(content={"app": "canvasdesk", "version": APP_VERSION})

    @app.post("/_control/namespaces/{namespace}/mutate")
    def control_mutate(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_canvasdesk_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_canvasdesk_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        result = canvasdesk.apply_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/mutation-intent")
    def control_mutation_intent(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_canvasdesk_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_canvasdesk_control)
        result = canvasdesk.arm_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/prepare")
    def control_prepare(
        namespace: str,
        payload: Annotated[PreparePayload, Body()],
        x_canvasdesk_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_canvasdesk_control)
        canvasdesk.prepare(
            namespace,
            accounts=payload.accounts,
            cells=[row.model_dump() for row in payload.cells],
        )
        return JSONResponse(content=canvasdesk.state(namespace))

    @app.post("/_control/namespaces/{namespace}/reset")
    def control_reset(namespace: str, x_canvasdesk_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_canvasdesk_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        canvasdesk.reset(namespace)
        return JSONResponse(content=canvasdesk.state(namespace))

    @app.post("/_control/namespaces/{namespace}/cleanup")
    def control_cleanup(namespace: str, x_canvasdesk_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_canvasdesk_control)
        removed = canvasdesk.cleanup(namespace)
        return JSONResponse(content={"namespace": namespace, "removed": removed})

    @app.get("/_control/namespaces/{namespace}/state")
    def control_state(namespace: str, x_canvasdesk_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_canvasdesk_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=canvasdesk.state(namespace))

    @app.get("/_control/namespaces/{namespace}/probe")
    def control_probe(namespace: str, x_canvasdesk_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_canvasdesk_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=canvasdesk.probe(namespace))

    return app
