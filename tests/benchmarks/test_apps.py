from __future__ import annotations

import hashlib
import time
from pathlib import Path

from playwright.async_api import Page, expect

from agentqa.platform.fixtures import (
    CanvasdeskFixture,
    ShopflowFixture,
    canvasdesk_password,
    shopflow_password,
    synthetic_password,
)
from tests.support.browser import chromium_page, run_async
from tests.support.canvasdesk import CanvasdeskServer
from tests.support.shopflow import ShopflowServer
from tests.support.taskboard import TaskboardServer

UPLOAD_FILE = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "data" / "uploads" / "mau-don.txt"


def poll_probe(fixture, fixture_ref: str, namespace: str, predicate, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    probe = fixture.probe(namespace)
    while time.monotonic() < deadline and not predicate(probe):
        time.sleep(0.1)
        probe = fixture.probe(namespace)
    assert predicate(probe), probe
    return probe


async def login_shopflow(page: Page, server: ShopflowServer, namespace: str) -> None:
    await page.goto(f"{server.base_url}/{namespace}/login")
    await page.get_by_label("Tài khoản").fill("alice")
    await page.get_by_label("Mật khẩu").fill(shopflow_password(namespace, "alice"))
    await page.get_by_role("button", name="Đăng nhập").click()
    await page.wait_for_url(f"**/{namespace}/catalog")


async def login_canvasdesk(page: Page, server: CanvasdeskServer, namespace: str) -> None:
    await page.goto(f"{server.base_url}/{namespace}/login")
    await page.get_by_label("Tài khoản").fill("alice")
    await page.get_by_label("Mật khẩu").fill(canvasdesk_password(namespace, "alice"))
    await page.get_by_role("button", name="Đăng nhập").click()
    await page.wait_for_url(f"**/{namespace}/board")


def test_taskboard_create_delete_roundtrip(taskboard_server: TaskboardServer, benchmark_registry) -> None:
    namespace = "apps-tb-roundtrip"
    assert benchmark_registry.prepare("taskboard@1", namespace).ok
    item_name = "Việc kiểm thử app"

    async def scenario() -> None:
        async with chromium_page() as page:
            await page.goto(f"{taskboard_server.base_url}/{namespace}/login")
            await page.get_by_label("Tài khoản").fill("alice")
            await page.get_by_label("Mật khẩu").fill(synthetic_password(namespace, "alice"))
            await page.get_by_role("button", name="Đăng nhập").click()
            await page.wait_for_url(f"**/{namespace}/tasks")
            await page.get_by_label("Việc mới").fill(item_name)
            await page.get_by_role("button", name="Thêm việc", exact=True).click()
            expect_rows = page.locator("#task-list li")
            await expect(expect_rows).to_have_count(1)
            await page.get_by_role("button", name="Xoá").click()
            await expect(expect_rows).to_have_count(0)

    run_async(scenario())
    probe = benchmark_registry.probe("taskboard@1", namespace)
    assert probe["counters"].get("item_created") == 1
    assert probe["counters"].get("item_deleted") == 1
    assert probe["item_count"] == 0


def test_shopflow_search_filter_with_network_call(
    shopflow_server: ShopflowServer, shopflow_fixture: ShopflowFixture
) -> None:
    namespace = "apps-sf-search"
    assert shopflow_fixture.prepare(namespace, seed="catalog_default").ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_shopflow(page, shopflow_server, namespace)
            await page.get_by_label("Tìm sản phẩm").fill("Bút")
            await page.get_by_label("Chỉ còn hàng").check()
            await page.get_by_label("Danh mục").select_option("van-phong")
            await page.get_by_role("button", name="Tìm").click()
            rows = page.locator("#catalog-list li")
            await expect(rows).to_have_count(2)

    run_async(scenario())
    probe = shopflow_fixture.probe(namespace)
    assert probe["counters"].get("search_performed") == 1
    assert probe["cart_line_count"] == 0


def test_shopflow_cart_qty_and_async_checkout(
    shopflow_server: ShopflowServer, shopflow_fixture: ShopflowFixture
) -> None:
    namespace = "apps-sf-checkout"
    assert shopflow_fixture.prepare(namespace, seed="catalog_default").ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_shopflow(page, shopflow_server, namespace)
            await page.get_by_label("Tìm sản phẩm").fill("Ly")
            await page.get_by_role("button", name="Tìm").click()
            await page.get_by_role("button", name="Thêm Ly thuỷ tinh vào giỏ").click()
            await page.wait_for_url(f"**/{namespace}/cart")
            await expect(page.locator("#cart-list .cart-relation")).to_have_text("Sản phẩm: Ly thuỷ tinh")
            await page.get_by_label("Số lượng Ly thuỷ tinh").select_option("2")
            await expect(page.get_by_label("Số lượng Ly thuỷ tinh")).to_have_value("2")
            await page.get_by_role("button", name="Thanh toán").click()
            await expect(page.locator(".job-status")).to_be_visible()
            await page.wait_for_url(f"**/{namespace}/orders", timeout=15000)
            await expect(page.locator("#order-list .order-status")).to_have_text("confirmed")

    run_async(scenario())
    probe = shopflow_fixture.probe(namespace)
    assert probe["counters"].get("cart_line_added") == 1
    assert probe["counters"].get("cart_qty_changed") == 1
    assert probe["counters"].get("checkout_settled") == 1
    assert probe["order_count"] == 1
    assert probe["cart_line_count"] == 0
    assert probe["last_write_ref"].startswith("sf-")


def test_shopflow_stock_rejected_and_empty_checkout(
    shopflow_server: ShopflowServer, shopflow_fixture: ShopflowFixture
) -> None:
    namespace = "apps-sf-reject"
    assert shopflow_fixture.prepare(namespace, seed="catalog_default").ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_shopflow(page, shopflow_server, namespace)
            await page.get_by_label("Tìm sản phẩm").fill("Bình")
            await page.get_by_role("button", name="Tìm").click()
            await page.get_by_role("button", name="Thêm Bình giữ nhiệt vào giỏ").click()
            await expect(page.locator(".cart-error")).to_have_text("Không thể thêm: hết hàng")
            await page.goto(f"{shopflow_server.base_url}/{namespace}/cart")
            await page.get_by_role("button", name="Thanh toán").click()
            await expect(page.locator(".cart-error")).to_have_text("Giỏ hàng trống")

    run_async(scenario())
    probe = shopflow_fixture.probe(namespace)
    assert probe["counters"].get("cart_rejected") == 1
    assert probe["counters"].get("checkout_rejected") == 1
    assert probe["counters"].get("cart_line_added", 0) == 0
    assert probe["cart_line_count"] == 0


def test_shopflow_upload_download_frame_and_tab(
    shopflow_server: ShopflowServer, shopflow_fixture: ShopflowFixture
) -> None:
    namespace = "apps-sf-lab"
    assert shopflow_fixture.prepare(namespace, seed="catalog_default").ok
    expected_invoice = "Hoá đơn Shopflow synthetic\nCảm ơn quý khách.\n"

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_shopflow(page, shopflow_server, namespace)
            await page.goto(f"{shopflow_server.base_url}/{namespace}/lab")
            await page.locator("#lab-dbl").dblclick()
            await expect(page.locator("#dbl-count")).to_have_text("1")
            await page.locator("#lab-hover").hover()
            await expect(page.locator("#hover-secret")).to_be_visible()
            await page.get_by_label("Ô nhập mã").type("z")
            await page.get_by_label("Ô nhập mã").press("a")
            await expect(page.locator("#lab-press-echo")).to_have_text("key:a")
            await page.locator("#scroll-bottom").scroll_into_view_if_needed()
            frame = page.frame(name="khung-thanh-toan")
            assert frame is not None
            await frame.get_by_role("button", name="Xác nhận khung").click()
            await expect(frame.locator("#frame-confirm")).to_have_text("Đã xác nhận")
            await page.set_input_files("#lab-file", str(UPLOAD_FILE))
            await page.get_by_role("button", name="Gửi tệp").click()
            await expect(page.locator("#lab-file-name")).to_have_text("mau-don.txt")
            async with page.expect_download() as download_info:
                await page.get_by_role("link", name="Tải hoá đơn").click()
            download = await download_info.value
            assert download.suggested_filename == "hoa-don-shopflow.txt"
            path = await download.path()
            data = Path(path).read_text(encoding="utf-8")
            assert data == expected_invoice

    run_async(scenario())
    probe = poll_probe(shopflow_fixture, "shopflow@1", namespace, lambda p: p["counters"].get("upload_received") == 1)
    assert probe["counters"].get("download_served") == 1
    assert probe["last_write_ref"].startswith("sf-")


def test_canvasdesk_hotspot_and_theme(
    canvasdesk_server: CanvasdeskServer, canvasdesk_fixture: CanvasdeskFixture
) -> None:
    namespace = "apps-cd-visual"
    assert canvasdesk_fixture.prepare(namespace, seed="default").ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_canvasdesk(page, canvasdesk_server, namespace)
            await page.get_by_role("button", name="Ô B").click()
            await expect(page.locator("#selection-status")).to_have_text("Đang chọn: Ô B")
            await expect(page.get_by_role("button", name="Ô B")).to_have_attribute("data-selected", "true")
            await page.get_by_role("button", name="Đổi nền").click()
            await expect(page.locator("#board-stage")).to_have_attribute("data-theme", "dark")

    run_async(scenario())
    probe = canvasdesk_fixture.probe(namespace)
    assert probe["counters"].get("hotspot_selected") == 1
    assert probe["counters"].get("theme_toggled") == 1
    assert probe["selected_ref"].startswith("cd-")
    assert probe["theme"] == "dark"


def test_canvasdesk_scroll_and_delayed_render(
    canvasdesk_server: CanvasdeskServer, canvasdesk_fixture: CanvasdeskFixture
) -> None:
    namespace = "apps-cd-delay"
    assert canvasdesk_fixture.prepare(namespace, seed="default").ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login_canvasdesk(page, canvasdesk_server, namespace)
            await expect(page.locator("#delayed-widget")).to_be_visible(timeout=5000)
            await expect(page.locator("#delayed-widget")).to_have_text("Tiện ích đã sẵn sàng")
            await page.locator("#reveal-done").scroll_into_view_if_needed()
            await page.get_by_role("button", name="Hoàn tất bố cục").click()
            await expect(page.locator("#layout-status")).to_have_text("Bố cục đã xác nhận")

    run_async(scenario())
    probe = poll_probe(
        canvasdesk_fixture,
        "canvasdesk@1",
        namespace,
        lambda p: p["counters"].get("delayed_rendered") == 1 and p["layout_confirmed"],
    )
    assert probe["counters"].get("layout_confirmed") == 1
    digest = hashlib.sha256(UPLOAD_FILE.read_bytes()).hexdigest()
    assert digest  # upload fixture asset tồn tại và đọc được
