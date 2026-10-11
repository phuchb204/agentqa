from __future__ import annotations

import asyncio
import html
import secrets
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from taskboard.state import NamespaceError, TaskboardStore

SESSION_COOKIE = "tb_session"
CONTROL_HEADER = "x-taskboard-control"
ASYNC_DELAY_SECONDS = 0.3
APP_VERSION = 1


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemSeed(StrictPayload):
    label: str
    done: bool = False


class PreparePayload(StrictPayload):
    accounts: dict[str, str] = {}
    items: list[ItemSeed] = []
    duplicate_policy: Literal["allow", "reject"] = "allow"


class MutationPayload(StrictPayload):
    operator: str
    params: dict[str, Any] = {}


def _page(title: str, body: str, refresh_seconds: int | None = None) -> HTMLResponse:
    refresh = ""
    if refresh_seconds is not None:
        refresh = f'<meta http-equiv="refresh" content="{refresh_seconds}">'
    document = (
        "<!doctype html>\n"
        '<html lang="vi">\n'
        '<head><meta charset="utf-8">' + refresh + "<title>" + html.escape(title) + "</title></head>\n"
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
    return _page("Đăng nhập Taskboard", body)


def _render_items(namespace: str, store: TaskboardStore) -> str:
    state = store.state(namespace)
    mutation = state.get("mutation") or {}
    patch = mutation.get("patch") or {}
    delete_label = "Xoá"
    if mutation.get("operator") == "rename_label":
        delete_label = str(patch.get("to", delete_label))
    rows = []
    for item in state["items"]:
        item_id = html.escape(item["id"], quote=True)
        rendered_id = item_id
        label = html.escape(item["label"])
        status = "Đã xong" if item["done"] else "Chưa xong"
        rows.append(
            f'<li data-item-id="{rendered_id}"><span class="item-label">{label}</span> '
            f'<span class="item-status">{status}</span>'
            f'<form method="post" action="/{namespace}/tasks/{item_id}/toggle">'
            '<button type="submit">Đổi trạng thái</button></form>'
            f'<form method="post" action="/{namespace}/tasks/{item_id}/relabel">'
            f'<label for="relabel-{item_id}">Nhãn mới</label>'
            f'<input id="relabel-{item_id}" name="label" type="text">'
            '<button type="submit">Đổi nhãn</button></form>'
            f'<form method="post" action="/{namespace}/tasks/{item_id}/delete">'
            f'<button type="submit" data-item-id="{item_id}">{html.escape(delete_label)}</button></form></li>'
        )
    listing = '<ul id="task-list">' + "".join(rows) + "</ul>"
    return (
        f'<form method="post" action="/{namespace}/tasks">'
        '<label for="new-label">Việc mới</label>'
        '<input id="new-label" name="label" type="text">'
        '<button type="submit" name="action" value="create">Thêm việc</button>'
        '<button type="submit" name="action" value="async">Thêm việc không chờ</button>'
        "</form>" + listing
    )


LAB_SCRIPT = """
<script>
let dbl = 0;
document.getElementById('lab-dbl').addEventListener('dblclick', () => {
  dbl += 1;
  document.getElementById('dbl-count').textContent = String(dbl);
});
const text = document.getElementById('lab-text');
text.addEventListener('input', () => { document.getElementById('lab-echo').textContent = text.value; });
const press = document.getElementById('lab-press');
press.addEventListener('keydown', (event) => {
  document.getElementById('lab-press-echo').textContent = 'key:' + event.key;
});
const select = document.getElementById('lab-select');
select.addEventListener('change', () => {
  document.getElementById('lab-select-value').textContent = select.value;
});
document.getElementById('lab-hover').addEventListener('mouseover', () => {
  document.getElementById('hover-secret').style.display = 'block';
});
document.getElementById('lab-file').addEventListener('change', () => {
  const files = document.getElementById('lab-file').files;
  document.getElementById('lab-file-name').textContent = files.length ? files[0].name : '';
});
document.getElementById('lab-dialog').addEventListener('click', () => {
  const ok = confirm('Xác nhận thao tác');
  document.getElementById('lab-dialog-result').textContent = ok ? 'đồng ý' : 'từ chối';
});
const host = document.getElementById('lab-shadow-host');
const shadow = host.attachShadow({ mode: 'open' });
shadow.innerHTML = '<button id="shadow-btn">Nút shadow</button>';
let shadowCount = 0;
shadow.getElementById('shadow-btn').addEventListener('click', () => {
  shadowCount += 1;
  document.getElementById('lab-shadow-count').textContent = String(shadowCount);
});
</script>
"""


def _render_lab(namespace: str) -> str:
    return (
        '<p id="dbl-count">0</p><button id="lab-dbl">Nhấp đôi</button>'
        '<p><input id="lab-text" type="text" aria-label="Ô nhập văn bản"></p>'
        '<p id="lab-echo"></p>'
        '<p><input id="lab-press" type="text" aria-label="Ô nhập phím"></p>'
        '<p id="lab-press-echo"></p>'
        '<p><input type="checkbox" id="lab-check"><label for="lab-check">Bật</label></p>'
        '<p><select id="lab-select" aria-label="Chọn mục"><option value="">--</option>'
        '<option value="mot">Một</option><option value="hai">Hai</option></select></p>'
        '<p id="lab-select-value"></p>'
        '<div id="lab-hover" role="button">Vùng rê</div>'
        '<p id="hover-secret" style="display:none">Đã rê thấy</p>'
        '<div id="lab-scroll" style="height:80px;overflow:auto"><div style="height:600px"></div>'
        '<p id="scroll-bottom">Cuối vùng cuộn</p></div>'
        '<p><input type="file" id="lab-file" aria-label="Tệp tải lên"></p>'
        '<p id="lab-file-name"></p>'
        '<button id="lab-dialog">Mở hộp thoại</button><p id="lab-dialog-result"></p>'
        f'<p><a id="lab-download" href="/{namespace}/lab/download" download="bao-cao.txt">Tải báo cáo</a></p>'
        f'<p><a id="lab-newtab" href="/{namespace}/lab/aux" target="_blank">Mở tab phụ</a></p>'
        f'<iframe id="lab-frame" name="lab-frame" src="/{namespace}/lab/frame" width="320" height="120"></iframe>'
        '<p><span id="lab-shadow-count">0</span></p>'
        '<div id="lab-shadow-host"></div>' + LAB_SCRIPT
    )


def _jobs_page(namespace: str, job_id: str, store: TaskboardStore) -> Any:
    state = store.state(namespace)
    job = state["jobs"].get(job_id)
    if job is None:
        return _page("Tiến trình không tồn tại", '<p class="job-missing">Không tìm thấy tiến trình.</p>')
    if job["status"] != "pending":
        return RedirectResponse(url=f"/{namespace}/tasks", status_code=303)
    body = (
        '<p class="job-status">Đang xử lý</p>'
        f'<p class="job-id">{html.escape(job_id)}</p>'
        f'<p><a href="/{namespace}/tasks">Danh sách việc</a></p>'
    )
    return _page("Tiến trình tạo việc", body, refresh_seconds=1)


def create_taskboard_app(control_token: str, store: TaskboardStore | None = None) -> FastAPI:
    app = FastAPI(title="Taskboard fixture", version=str(APP_VERSION))
    taskboard = store if store is not None else TaskboardStore()
    sessions: dict[str, tuple[str, str]] = {}
    app.state.taskboard = taskboard
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
        if not taskboard.exists(namespace):
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
        if not taskboard.authenticate(namespace, username, password):
            taskboard.record(namespace, "login_failed", entity_label=username)
            return _login_page(namespace, "Sai tài khoản hoặc mật khẩu")
        token = secrets.token_urlsafe(24)
        sessions[token] = (namespace, username)
        taskboard.record(namespace, "login", entity_label=username)
        response = RedirectResponse(url=f"/{namespace}/tasks", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return response

    @app.post("/{namespace}/logout")
    def logout(request: Request, namespace: str) -> Any:
        token = request.cookies.get(SESSION_COOKIE)
        if token is not None:
            sessions.pop(token, None)
        response = RedirectResponse(url=f"/{namespace}/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/{namespace}/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Danh sách việc", _render_items(namespace, taskboard))

    @app.post("/{namespace}/tasks")
    async def tasks_submit(
        request: Request,
        namespace: str,
        action: Annotated[str, Form()],
        label: Annotated[str, Form()] = "",
    ) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        if action == "async":
            job = taskboard.submit_async(namespace, label)
            mutation = taskboard.mutation(namespace) or {}
            delay = float((mutation.get("patch") or {}).get("seconds", ASYNC_DELAY_SECONDS))
            asyncio.get_running_loop().create_task(_complete_async(namespace, job.id, delay))
            return _jobs_page(namespace, job.id, taskboard)
        if label.startswith("slow-"):
            await asyncio.sleep(0.8)
        created, _item = taskboard.create_item(namespace, label)
        if not created:
            body = _render_items(namespace, taskboard)
            return _page("Danh sách việc", f'<p class="form-error">Nhãn không hợp lệ hoặc đã tồn tại</p>{body}')
        return _page("Danh sách việc", _render_items(namespace, taskboard))

    async def _complete_async(namespace: str, job_id: str, delay: float = ASYNC_DELAY_SECONDS) -> None:
        await asyncio.sleep(max(0.0, delay))
        taskboard.settle_async(namespace, job_id)

    @app.get("/{namespace}/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, namespace: str, job_id: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _jobs_page(namespace, job_id, taskboard)

    @app.post("/{namespace}/tasks/{item_id}/relabel")
    def relabel(request: Request, namespace: str, item_id: str, label: Annotated[str, Form()] = "") -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        taskboard.relabel_item(namespace, item_id, label)
        return _page("Danh sách việc", _render_items(namespace, taskboard))

    @app.post("/{namespace}/tasks/{item_id}/toggle")
    def toggle(request: Request, namespace: str, item_id: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        taskboard.toggle_item(namespace, item_id)
        return _page("Danh sách việc", _render_items(namespace, taskboard))

    @app.post("/{namespace}/tasks/{item_id}/delete")
    def delete(request: Request, namespace: str, item_id: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        taskboard.delete_item(namespace, item_id)
        return _page("Danh sách việc", _render_items(namespace, taskboard))

    @app.get("/{namespace}/lab", response_class=HTMLResponse)
    def lab_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Phòng thao tác", _render_lab(namespace))

    @app.get("/{namespace}/lab/aux", response_class=HTMLResponse)
    def lab_aux(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Trang phụ", '<p id="aux-marker">Trang phụ đã mở</p>')

    @app.get("/{namespace}/lab/frame", response_class=HTMLResponse)
    def lab_frame(request: Request, namespace: str) -> Any:
        return _page(
            "Khung phụ",
            '<button id="frame-btn" onclick="this.textContent=\'Đã bấm\'">Nút trong khung</button>',
        )

    @app.get("/{namespace}/lab/download")
    def lab_download(request: Request, namespace: str) -> Any:
        return PlainTextResponse(
            "Nội dung báo cáo kiểm thử",
            headers={"Content-Disposition": 'attachment; filename="bao-cao.txt"'},
        )

    @app.get("/_control/version")
    def control_version(x_taskboard_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_taskboard_control)
        return JSONResponse(content={"app": "taskboard", "version": APP_VERSION})

    @app.post("/_control/namespaces/{namespace}/mutate")
    def control_mutate(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_taskboard_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_taskboard_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        result = taskboard.apply_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/mutation-intent")
    def control_mutation_intent(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_taskboard_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_taskboard_control)
        result = taskboard.arm_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/prepare")
    def control_prepare(
        namespace: str,
        payload: Annotated[PreparePayload, Body()],
        x_taskboard_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_taskboard_control)
        taskboard.prepare(
            namespace,
            accounts=payload.accounts,
            items=[seed.model_dump() for seed in payload.items],
            duplicate_policy=payload.duplicate_policy,
        )
        return JSONResponse(content=taskboard.state(namespace))

    @app.post("/_control/namespaces/{namespace}/reset")
    def control_reset(namespace: str, x_taskboard_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_taskboard_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        taskboard.reset(namespace)
        return JSONResponse(content=taskboard.state(namespace))

    @app.post("/_control/namespaces/{namespace}/cleanup")
    def control_cleanup(namespace: str, x_taskboard_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_taskboard_control)
        removed = taskboard.cleanup(namespace)
        return JSONResponse(content={"namespace": namespace, "removed": removed})

    @app.get("/_control/namespaces/{namespace}/state")
    def control_state(namespace: str, x_taskboard_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_taskboard_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=taskboard.state(namespace))

    @app.get("/_control/namespaces/{namespace}/probe")
    def control_probe(namespace: str, x_taskboard_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_taskboard_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=taskboard.probe(namespace))

    return app
