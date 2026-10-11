from __future__ import annotations

import asyncio
import html
import secrets
from typing import Annotated, Any

from fastapi import Body, FastAPI, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from shopflow.state import NamespaceError, ShopflowStore

SESSION_COOKIE = "sf_session"
CONTROL_HEADER = "x-shopflow-control"
SETTLE_DELAY_SECONDS = 0.3
APP_VERSION = 1

CATEGORY_LABELS = {"": "Tất cả", "van-phong": "Văn phòng", "do-gia-dung": "Đồ gia dụng"}


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogSeed(StrictPayload):
    id: str
    name: str
    category: str = "van-phong"
    price: int = 0
    stock: int = 0


class PreparePayload(StrictPayload):
    accounts: dict[str, str] = {}
    catalog: list[CatalogSeed] = []


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


def _nav(namespace: str) -> str:
    return (
        f'<nav><a href="/{namespace}/catalog">Cửa hàng</a> | '
        f'<a href="/{namespace}/cart">Giỏ hàng</a> | '
        f'<a href="/{namespace}/orders">Đơn hàng</a> | '
        f'<a href="/{namespace}/lab">Phòng thao tác</a></nav>'
    )


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
    return _page("Đăng nhập Shopflow", body)


CATALOG_SCRIPT = """
<script>
const searchButton = document.getElementById('search-button');
const searchInput = document.getElementById('search-input');
const categorySelect = document.getElementById('category-select');
const stockCheckbox = document.getElementById('stock-only');
const resultList = document.getElementById('catalog-list');
function renderRows(rows) {
  resultList.innerHTML = '';
  for (const row of rows) {
    const li = document.createElement('li');
    li.setAttribute('data-product-id', row.id);
    li.innerHTML =
      '<span class="product-name">' + row.name + '</span> ' +
      '<span class="product-stock">Kho: ' + row.stock + '</span> ' +
      '<button type="button" class="add-to-cart">Thêm ' + row.name + ' vào giỏ</button>';
    li.querySelector('.add-to-cart').addEventListener('click', () => {
      const form = document.getElementById('add-form');
      form.querySelector('input[name=product_id]').value = row.id;
      form.submit();
    });
    resultList.appendChild(li);
  }
}
async function runSearch() {
  const params = new URLSearchParams();
  params.set('q', searchInput.value);
  if (categorySelect.value) { params.set('category', categorySelect.value); }
  if (stockCheckbox.checked) { params.set('stock', '1'); }
  const response = await fetch(location.pathname.replace('/catalog', '/api/search') + '?' + params.toString());
  const payload = await response.json();
  renderRows(payload.results);
}
searchButton.addEventListener('click', runSearch);
</script>
"""


def _catalog_page(namespace: str) -> str:
    category_options = "".join(
        f'<option value="{value}">{html.escape(label)}</option>' for value, label in CATEGORY_LABELS.items()
    )
    body = (
        '<form onsubmit="return false">'
        '<label for="search-input">Tìm sản phẩm</label> '
        '<input id="search-input" name="q" type="text"> '
        '<label for="category-select">Danh mục</label> '
        f'<select id="category-select" name="category">{category_options}</select> '
        '<input type="checkbox" id="stock-only" name="stock">'
        '<label for="stock-only">Chỉ còn hàng</label> '
        '<button type="button" id="search-button">Tìm</button>'
        "</form>"
        '<form method="post" action="' + f"/{namespace}/cart/lines" + '" id="add-form">'
        '<input type="hidden" name="product_id" value="">'
        '<input type="hidden" name="qty" value="1">'
        "</form>"
        '<ul id="catalog-list"></ul>' + CATALOG_SCRIPT
    )
    return _nav(namespace) + body


def _cart_rows(namespace: str, store: ShopflowStore) -> str:
    state = store.state(namespace)
    rows = []
    for line in state["cart"]:
        ref = html.escape(line["ref"], quote=True)
        product = next((row for row in state["catalog"] if row["id"] == line["product_id"]), None)
        product_name = product["name"] if product else line["product_id"]
        options = "".join(
            f'<option value="{value}"{" selected" if value == line["qty"] else ""}>{value}</option>'
            for value in (1, 2, 3)
        )
        rows.append(
            f'<li data-line-ref="{ref}"><span class="cart-relation">Sản phẩm: {html.escape(product_name)}</span> '
            f'<form method="post" action="/{namespace}/cart/lines/{ref}/qty">'
            f'<label for="qty-{ref}">Số lượng {html.escape(product_name)}</label>'
            f'<select id="qty-{ref}" class="line-qty" name="qty" onchange="this.form.submit()">{options}</select>'
            "</form>"
            f'<form method="post" action="/{namespace}/cart/lines/{ref}/remove">'
            f'<button type="submit">Xoá {html.escape(product_name)}</button></form>'
            f'<form method="post" action="/{namespace}/cart/lines/{ref}/qty">'
            f'<input type="hidden" name="qty" value="{min(3, line["qty"] + 1)}">'
            f'<button type="submit">Tăng {html.escape(product_name)}</button></form></li>'
        )
    if not rows:
        rows.append('<li id="cart-empty">Giỏ hàng trống</li>')
    return '<ul id="cart-list">' + "".join(rows) + "</ul>"


def _cart_page(namespace: str, store: ShopflowStore, error: str | None = None) -> str:
    error_html = f'<p class="cart-error">{html.escape(error)}</p>' if error else ""
    body = (
        error_html
        + _cart_rows(namespace, store)
        + f'<form method="post" action="/{namespace}/cart/checkout">'
        + '<button type="submit">Thanh toán</button></form>'
    )
    return _nav(namespace) + body


def _orders_page(namespace: str, store: ShopflowStore) -> str:
    state = store.state(namespace)
    rows = []
    for order in state["orders"]:
        names = []
        for line in order["lines"]:
            product = next((row for row in state["catalog"] if row["id"] == line["product_id"]), None)
            names.append(f"{product['name'] if product else line['product_id']} x{line['qty']}")
        rows.append(
            f'<li data-order-ref="{html.escape(order["ref"], quote=True)}" class="order-row">'
            f'<span class="order-status">{html.escape(order["status"])}</span> '
            f'<span class="order-lines">{" ; ".join(html.escape(name) for name in names)}</span></li>'
        )
    if not rows:
        rows.append('<li id="orders-empty">Chưa có đơn hàng</li>')
    return _nav(namespace) + '<ul id="order-list">' + "".join(rows) + "</ul>"


def _job_page(namespace: str, job_ref: str, store: ShopflowStore) -> Any:
    state = store.state(namespace)
    job = next((item for item in state["jobs"] if item["ref"] == job_ref), None)
    if job is None:
        return _page("Tiến trình không tồn tại", '<p class="job-missing">Không tìm thấy tiến trình.</p>')
    if job["status"] != "pending":
        return RedirectResponse(url=f"/{namespace}/orders", status_code=303)
    body = (
        '<p class="job-status">Đang xử lý đơn</p>'
        f'<p class="job-ref">{html.escape(job_ref)}</p>'
        f'<p><a href="/{namespace}/orders">Danh sách đơn</a></p>'
    )
    return _page("Tiến trình thanh toán", body, refresh_seconds=1)


LAB_SCRIPT = """
<script>
const scrollBox = document.getElementById('lab-scroll');
scrollBox.addEventListener('scroll', () => {
  document.getElementById('scroll-position').textContent = String(Math.round(scrollBox.scrollTop));
});
document.getElementById('lab-hover').addEventListener('mouseover', () => {
  document.getElementById('hover-secret').style.display = 'block';
});
const press = document.getElementById('lab-press');
press.addEventListener('keydown', (event) => {
  document.getElementById('lab-press-echo').textContent = 'key:' + event.key;
});
document.getElementById('lab-dbl').addEventListener('dblclick', () => {
  const node = document.getElementById('dbl-count');
  node.textContent = String(Number(node.textContent) + 1);
});
document.getElementById('lab-file').addEventListener('change', () => {
  const files = document.getElementById('lab-file').files;
  document.getElementById('lab-file-name').textContent = files.length ? files[0].name : '';
});
</script>
"""


def _render_lab(namespace: str) -> str:
    return (
        '<p><span id="dbl-count">0</span> lượt nhấp đôi</p><button id="lab-dbl">Tăng nhanh</button>'
        '<p id="lab-scroll" style="height:80px;overflow:auto"><div style="height:600px"></div>'
        '<p id="scroll-bottom">Cuối danh mục</p></div>'
        '<p id="scroll-position">0</p>'
        '<div id="lab-hover" role="button">Vùng rê</div>'
        '<p id="hover-secret" style="display:none">Đã rê thấy mã giảm giá</p>'
        '<p><input id="lab-press" type="text" aria-label="Ô nhập mã"></p>'
        '<p id="lab-press-echo"></p>'
        f'<iframe id="lab-frame" name="khung-thanh-toan" src="/{namespace}/lab/frame" '
        'width="320" height="120"></iframe>'
        f'<p><a id="lab-newtab" href="/{namespace}/lab/aux" target="_blank">Mở tab phụ</a></p>'
        '<form method="post" action="/' + namespace + '/lab/upload" enctype="multipart/form-data">'
        '<label for="lab-file">Tệp đính kèm</label>'
        '<input type="file" id="lab-file" name="file" aria-label="Tệp đính kèm">'
        '<button type="submit">Gửi tệp</button></form>'
        '<p id="lab-file-name"></p>'
        f'<p><a id="lab-download" href="/{namespace}/lab/invoice" download="hoa-don-shopflow.txt">Tải hoá đơn</a></p>'
        + LAB_SCRIPT
    )


def create_shopflow_app(control_token: str, store: ShopflowStore | None = None) -> FastAPI:
    app = FastAPI(title="Shopflow fixture", version=str(APP_VERSION))
    shopflow = store if store is not None else ShopflowStore()
    sessions: dict[str, tuple[str, str]] = {}
    app.state.shopflow = shopflow
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
        if not shopflow.exists(namespace):
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
        if not shopflow.authenticate(namespace, username, password):
            shopflow.record(namespace, "login_failed", detail=username)
            return _login_page(namespace, "Sai tài khoản hoặc mật khẩu")
        token = secrets.token_urlsafe(24)
        sessions[token] = (namespace, username)
        shopflow.record(namespace, "login", detail=username)
        response = RedirectResponse(url=f"/{namespace}/catalog", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return response

    @app.get("/{namespace}/catalog", response_class=HTMLResponse)
    def catalog_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Cửa hàng", _catalog_page(namespace))

    @app.get("/{namespace}/api/search")
    def api_search(
        request: Request,
        namespace: str,
        q: str = "",
        category: str | None = None,
        stock: str | None = None,
    ) -> JSONResponse:
        if session_namespace(request, namespace) is None:
            return JSONResponse(status_code=401, content={"error": "chưa đăng nhập"})
        results = shopflow.search(namespace, q, category=category or None, in_stock_only=stock == "1")
        return JSONResponse(content={"results": results})

    @app.post("/{namespace}/cart/lines")
    def cart_add(
        request: Request,
        namespace: str,
        product_id: Annotated[str, Form()],
        qty: Annotated[int, Form()] = 1,
    ) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        ok, _reason = shopflow.add_to_cart(namespace, product_id, qty)
        if not ok:
            return _page("Giỏ hàng", _cart_page(namespace, shopflow, "Không thể thêm: hết hàng"))
        return RedirectResponse(url=f"/{namespace}/cart", status_code=303)

    @app.get("/{namespace}/cart", response_class=HTMLResponse)
    def cart_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Giỏ hàng", _cart_page(namespace, shopflow))

    @app.post("/{namespace}/cart/lines/{line_ref}/remove")
    def cart_remove(request: Request, namespace: str, line_ref: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        line_id = shopflow.find_line_id(namespace, line_ref)
        if line_id is not None:
            shopflow.remove_line(namespace, line_id)
        return RedirectResponse(url=f"/{namespace}/cart", status_code=303)

    @app.post("/{namespace}/cart/lines/{line_ref}/qty")
    def cart_qty(request: Request, namespace: str, line_ref: str, qty: Annotated[int, Form()]) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        line_id = shopflow.find_line_id(namespace, line_ref)
        if line_id is not None:
            shopflow.set_qty(namespace, line_id, qty)
        return RedirectResponse(url=f"/{namespace}/cart", status_code=303)

    @app.post("/{namespace}/cart/checkout")
    async def cart_checkout(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        ok, _reason = shopflow.submit_checkout(namespace)
        if not ok:
            return _page("Giỏ hàng", _cart_page(namespace, shopflow, "Giỏ hàng trống"))
        state = shopflow.state(namespace)
        job_ref = state["jobs"][-1]["ref"]
        mutation = shopflow.mutation(namespace) or {}
        delay = float((mutation.get("patch") or {}).get("seconds", SETTLE_DELAY_SECONDS))
        asyncio.get_running_loop().create_task(_settle(namespace, job_ref, delay))
        return RedirectResponse(url=f"/{namespace}/jobs/{job_ref}", status_code=303)

    async def _settle(namespace: str, job_ref: str, delay: float = SETTLE_DELAY_SECONDS) -> None:
        await asyncio.sleep(max(0.0, delay))
        job_id = shopflow.find_job_id(namespace, job_ref)
        if job_id is not None:
            shopflow.settle_checkout(namespace, job_id)

    @app.get("/{namespace}/jobs/{job_ref}", response_class=HTMLResponse)
    def job_page(request: Request, namespace: str, job_ref: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _job_page(namespace, job_ref, shopflow)

    @app.get("/{namespace}/orders", response_class=HTMLResponse)
    def orders_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Đơn hàng", _orders_page(namespace, shopflow))

    @app.get("/{namespace}/lab", response_class=HTMLResponse)
    def lab_page(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Phòng thao tác", _nav(namespace) + _render_lab(namespace))

    @app.get("/{namespace}/lab/aux", response_class=HTMLResponse)
    def lab_aux(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        return _page("Trang phụ", '<p id="aux-marker">Trang phụ đã mở</p>')

    @app.get("/{namespace}/lab/frame", response_class=HTMLResponse)
    def lab_frame(request: Request, namespace: str) -> Any:
        return _page(
            "Khung thanh toán",
            '<button id="frame-confirm" onclick="this.textContent=\'Đã xác nhận\'">Xác nhận khung</button>',
        )

    @app.post("/{namespace}/lab/upload")
    async def lab_upload(request: Request, namespace: str, file: UploadFile | None = None) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        if file is None:
            return _page("Phòng thao tác", _nav(namespace) + '<p class="upload-error">Thiếu tệp</p>')
        content = await file.read()
        shopflow.record_upload(namespace, file.filename or "tep", len(content))
        return _page(
            "Phòng thao tác",
            _nav(namespace)
            + _render_lab(namespace).replace(
                '<p id="lab-file-name"></p>', f'<p id="lab-file-name">{html.escape(file.filename or "tep")}</p>'
            ),
        )

    @app.get("/{namespace}/lab/invoice")
    def lab_invoice(request: Request, namespace: str) -> Any:
        if session_namespace(request, namespace) is None:
            return RedirectResponse(url=f"/{namespace}/login", status_code=303)
        shopflow.record_download(namespace)
        return PlainTextResponse(
            "Hoá đơn Shopflow synthetic\nCảm ơn quý khách.\n",
            headers={"Content-Disposition": 'attachment; filename="hoa-don-shopflow.txt"'},
        )

    @app.get("/_control/version")
    def control_version(x_shopflow_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_shopflow_control)
        return JSONResponse(content={"app": "shopflow", "version": APP_VERSION})

    @app.post("/_control/namespaces/{namespace}/mutate")
    def control_mutate(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_shopflow_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_shopflow_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        result = shopflow.apply_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/mutation-intent")
    def control_mutation_intent(
        namespace: str,
        payload: Annotated[MutationPayload, Body()],
        x_shopflow_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_shopflow_control)
        result = shopflow.arm_mutation(namespace, payload.operator, payload.params)
        return JSONResponse(content=result)

    @app.post("/_control/namespaces/{namespace}/prepare")
    def control_prepare(
        namespace: str,
        payload: Annotated[PreparePayload, Body()],
        x_shopflow_control: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_control(x_shopflow_control)
        shopflow.prepare(
            namespace,
            accounts=payload.accounts,
            catalog=[row.model_dump() for row in payload.catalog],
        )
        return JSONResponse(content=shopflow.state(namespace))

    @app.post("/_control/namespaces/{namespace}/reset")
    def control_reset(namespace: str, x_shopflow_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_shopflow_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        shopflow.reset(namespace)
        return JSONResponse(content=shopflow.state(namespace))

    @app.post("/_control/namespaces/{namespace}/cleanup")
    def control_cleanup(namespace: str, x_shopflow_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_shopflow_control)
        removed = shopflow.cleanup(namespace)
        return JSONResponse(content={"namespace": namespace, "removed": removed})

    @app.get("/_control/namespaces/{namespace}/state")
    def control_state(namespace: str, x_shopflow_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_shopflow_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=shopflow.state(namespace))

    @app.get("/_control/namespaces/{namespace}/probe")
    def control_probe(namespace: str, x_shopflow_control: Annotated[str | None, Header()] = None) -> JSONResponse:
        require_control(x_shopflow_control)
        missing = namespace_guard(namespace)
        if missing is not None:
            return missing
        return JSONResponse(content=shopflow.probe(namespace))

    return app
