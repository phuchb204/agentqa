from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tools.ui_harness.runner import HarnessCheck, HarnessError

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness

CANARY = "sk-ui-canary-never-render"


async def drive_admin_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict]:
    from playwright.async_api import async_playwright, expect

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    workspace_id = str(harness.seed.workspace_id)
    viewer_username, viewer_password = await _seed_viewer(harness)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(25000)
        console_lines: list[str] = []
        page.on("console", lambda message: console_lines.append(f"[console] {message.text}"))
        page.on("pageerror", lambda error: console_lines.append(f"[pageerror] {error}"))
        try:
            await page.goto(harness.web_base_url)
            await page.get_by_label("Tài khoản").fill(harness.seed.username)
            await page.get_by_label("Mật khẩu").fill(harness.seed.password)
            await page.get_by_role("button", name="Đăng nhập").click()
            await page.get_by_role("link", name="Cài đặt").wait_for()

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/settings/references")
            try:
                await page.get_by_test_id("settings-references").wait_for()
            except Exception:
                await page.screenshot(path=str(harness.workspace_root / "admin-settings-fail.png"))
                body = await page.evaluate("() => document.body.innerText")
                raise HarnessError(f"settings references không render: {body[:400]!r}") from None
            await page.get_by_label("Credential reference").fill("opencode_go")
            await page.get_by_label("Env var").fill("OPENCODE_GO_API_KEY")
            await page.get_by_role("button", name="Thêm reference").click()
            await page.get_by_text("Đã tạo credential reference").wait_for()
            if "v1" not in (await page.get_by_test_id("settings-references").inner_text()):
                raise HarnessError("thiếu version v1 sau khi tạo reference")
            checks.append(HarnessCheck("settings-owner-create", True, "owner tạo credential reference qua UI"))

            await page.get_by_label("Rotate reference").fill("opencode_go")
            await page.get_by_label("Giá trị mới").fill(CANARY)
            await page.get_by_role("button", name="Rotate").click()
            await page.get_by_text("Đã tạo version mới").wait_for()
            await expect(page.get_by_test_id("settings-references")).to_contain_text("v2", timeout=15000)
            references_text = await page.get_by_test_id("settings-references").inner_text()
            if "v2" not in references_text:
                raise HarnessError("rotation không tạo version v2")
            body_text = await page.evaluate("() => document.body.textContent || ''")
            if CANARY in body_text:
                raise HarnessError("giá trị credential canary xuất hiện trong DOM")
            api_text = await page.evaluate(
                """async (workspaceId) => {
                    const response = await fetch(`/api/v1/workspaces/${workspaceId}/credential-references`);
                    return await response.text();
                }""",
                workspace_id,
            )
            if CANARY in api_text:
                raise HarnessError("canary xuất hiện trong API credential list")
            checks.append(
                HarnessCheck("no-plaintext-read", True, "không hiển thị/không endpoint trả plaintext credential")
            )

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/settings/providers")
            await page.get_by_test_id("settings-providers").wait_for()
            providers_text = await page.get_by_test_id("settings-providers").inner_text()
            if "Đã cấu hình" not in providers_text:
                raise HarnessError("provider readiness không phản ánh credential active")
            if "deepseek-v4.1-flash" not in providers_text or "jev-1.13-free" not in providers_text:
                raise HarnessError("thiếu hai route cố định trong providers view")
            checks.append(HarnessCheck("provider-readiness", True, "readiness providers theo credential active"))

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/settings/workers")
            await page.get_by_test_id("settings-workers").wait_for()
            await page.get_by_text(re.compile("API:")).wait_for()
            checks.append(HarnessCheck("worker-health-visible", True, "health/live hiển thị, không suy diễn state"))

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/settings/references")
            await page.get_by_test_id("settings-references").wait_for()
            await page.get_by_role("button", name="Thu hồi").first.click()
            await page.get_by_text("Đã thu hồi credential reference").wait_for()
            references_after = await page.get_by_test_id("settings-references").inner_text()
            if "revoked" not in references_after:
                raise HarnessError("revoke không đổi status credential")
            checks.append(HarnessCheck("settings-owner-revoke", True, "revoke đổi status và vô hiệu grant"))

            await page.get_by_role("button", name="Menu người dùng").click()
            await page.get_by_role("menuitem", name="Đăng xuất").click()
            await page.get_by_label("Tài khoản").wait_for()
            await page.get_by_label("Tài khoản").fill(viewer_username)
            await page.get_by_label("Mật khẩu").fill(viewer_password)
            await page.get_by_role("button", name="Đăng nhập").click()
            await page.get_by_role("link", name="Cài đặt").wait_for()
            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/settings/references")
            await page.get_by_test_id("settings-references").wait_for()
            if await page.get_by_role("button", name="Thêm reference").count() > 0:
                raise HarnessError("viewer thấy nút thêm reference")
            if await page.get_by_role("button", name="Rotate").count() > 0:
                raise HarnessError("viewer thấy nút rotate")
            viewer_text = await page.get_by_test_id("settings-references").inner_text()
            if "chỉ đọc" not in viewer_text and "không có quyền" not in viewer_text:
                raise HarnessError(f"viewer không thấy thông báo quyền hạn: {viewer_text[:200]!r}")
            checks.append(HarnessCheck("viewer-readonly-settings", True, "viewer chỉ đọc settings, ẩn form"))

            denied_status = await page.evaluate(
                """async (workspaceId) => {
                    const response = await fetch(`/api/v1/workspaces/${workspaceId}/credential-references`);
                    return response.status;
                }""",
                workspace_id,
            )
            if denied_status != 403:
                raise HarnessError(f"viewer API không bị chặn: {denied_status}")
            checks.append(HarnessCheck("viewer-api-denied", True, "backend chặn viewer, không chỉ ẩn nút UI"))
        finally:
            await context.close()
            await browser.close()

    _ = console_lines
    return checks, {}


async def _seed_viewer(harness: UiHarness) -> tuple[str, str]:
    import asyncio

    return await asyncio.to_thread(harness.seed_viewer)
