from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from tools.ui_harness.runner import CANARY_KEY, ITEM_NAME, HarnessCheck, HarnessError, probe_from_events

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness

SOURCE_TEXT = (
    "# Luồng tạo việc\n\n"
    "Người dùng đăng nhập bằng tài khoản mẫu, mở trang danh sách việc, "
    "nhập tên việc mới và bấm Thêm việc. Việc mới xuất hiện đúng một lần trong danh sách."
)


async def drive_authoring_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict, dict | None]:
    from playwright.async_api import async_playwright

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    draft_state: dict = {}
    replay: dict | None = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(25000)
        try:
            await page.goto(harness.web_base_url)
            await page.get_by_label("Tài khoản").fill(harness.seed.username)
            await page.get_by_label("Mật khẩu").fill(harness.seed.password)
            await page.get_by_role("button", name="Đăng nhập").click()
            await page.get_by_role("link", name="Yêu cầu").wait_for()
            checks.append(HarnessCheck("role-aware-login", True, "đăng nhập và vào workspace qua UI"))

            await page.keyboard.press("Tab")
            focused = await page.evaluate("() => document.activeElement && document.activeElement.textContent")
            if not (focused and "Bỏ qua điều hướng" in str(focused)):
                raise HarnessError(f"focus không vào skip-link khi Tab: {focused!r}")
            checks.append(HarnessCheck("keyboard-focus", True, "Tab đầu tiên vào skip-link"))

            if CANARY_KEY in await page.content():
                raise HarnessError("canary xuất hiện trong UI")
            checks.append(HarnessCheck("no-inherited-provider-creds", True, "canary không xuất hiện trong UI"))

            await page.get_by_role("link", name="Yêu cầu").click()
            await page.get_by_role("link", name="create_item").click()
            await page.get_by_text("Revision mới nhất").wait_for()

            await page.get_by_label("Logical key nguồn mới").fill("flow_source")
            await page.get_by_role("button", name="Tạo nguồn").click()
            await page.get_by_label("Nguồn để upload").select_option(label="flow_source")
            source_file = harness.workspace_root / "flow_source.md"
            source_file.write_text(SOURCE_TEXT, encoding="utf-8")
            await page.get_by_label("File nguồn").set_input_files(str(source_file))
            await page.get_by_role("button", name="Upload an toàn").click()
            await page.get_by_text(re.compile("Đã trích xuất")).wait_for()
            checks.append(HarnessCheck("source-upload-quarantine", True, "upload an toàn và trích xuất segment"))

            await page.get_by_label("Mục tiêu đề xuất").fill("Tạo việc mới và xác nhận xuất hiện một lần")
            await page.get_by_label("Kỳ vọng đề xuất").fill("Việc mới xuất hiện đúng một lần trong danh sách")
            await page.get_by_label("Nguồn tham chiếu").select_option(label="flow_source")
            await page.get_by_role("button", name="Đề xuất ca").click()
            await page.get_by_text("Tạo việc mới và xác nhận xuất hiện một lần").first.wait_for()
            checks.append(HarnessCheck("authoring-proposal", True, "proposal typed từ fake model hiển thị"))

            await page.get_by_label("Logical key ca mới").fill("authored_create_item")
            await page.get_by_role("button", name="Áp dụng vào draft").click()
            await page.get_by_text("Diff áp dụng").wait_for()
            await page.get_by_role("button", name="Mở ca trong editor").click()
            await page.get_by_text("Draft v1").wait_for()
            checks.append(HarnessCheck("proposal-apply-diff", True, "proposal áp vào draft qua edit_version/diff"))

            await page.get_by_role("button", name="Promote…").click()
            await page.get_by_role("button", name="Promote revision").click()
            await page.get_by_text(re.compile("Đã promote revision 1")).wait_for()
            checks.append(HarnessCheck("promote-ready", True, "promote tạo revision ready với digest từ server"))

            await page.get_by_role("button", name="Chạy thử (provisional)").click()
            run_text = page.get_by_text(re.compile(r"run [0-9a-f]{8}"))
            await run_text.wait_for()
            run_label = await run_text.first.text_content() or ""
            match = re.search(r"run ([0-9a-f]{8})", run_label)
            if match is None:
                raise HarnessError(f"không đọc được run id provisional từ UI: {run_label!r}")
            draft_run_id = await asyncio.to_thread(harness.find_run_by_prefix, match.group(1))
            if draft_run_id is None:
                raise HarnessError("không tìm thấy draft run trong DB")
            draft_state = await asyncio.to_thread(harness.wait_for_run, draft_run_id)
            if "provisional" not in draft_state["reasons"]:
                raise HarnessError(f"draft run thiếu annotation provisional: {draft_state}")
            checks.append(
                HarnessCheck(
                    "draft-run-provisional",
                    True,
                    f"draft run {draft_run_id} verdict={draft_state['verdict']} reasons={draft_state['reasons']}",
                )
            )
            ready_count = await asyncio.to_thread(harness.ready_case_revision_count, "authored_create_item")
            if ready_count != 1:
                raise HarnessError("draft run đã tự tạo ready revision")
            checks.append(HarnessCheck("no-auto-ready", True, "draft run không tự tạo ready revision"))

            _, case_id = await asyncio.to_thread(harness.latest_case_revision, "authored_create_item")
            await asyncio.to_thread(harness.bump_draft_from_api, case_id, 1)
            title_input = page.get_by_label("Tiêu đề ca")
            await title_input.fill("Bản local đang sửa")
            await page.get_by_text("Xung đột phiên bản với server").wait_for()
            await page.get_by_role("button", name="Dùng bản server").click()
            await page.get_by_text("Xung đột phiên bản với server").wait_for(state="detached")
            if await title_input.input_value() != "Bản server đổi tiêu đề":
                raise HarnessError("resolve dùng bản server không cập nhật nội dung")
            checks.append(
                HarnessCheck("stale-edit-conflict", True, "xung đột If-Match hiển thị merge, không tự ghi đè")
            )
        except Exception as error:
            try:
                await page.screenshot(path=str(harness.workspace_root / "failure.png"), full_page=True)
                (harness.workspace_root / "failure.html").write_text(await page.content(), encoding="utf-8")
            except Exception:
                pass
            raise HarnessError(f"{error}") from error
        finally:
            await context.close()
            await browser.close()

    revision_id, _case_id = await asyncio.to_thread(harness.latest_case_revision, "authored_create_item")
    run_id = await asyncio.to_thread(harness.run_replay, revision_id)
    state = await asyncio.to_thread(harness.wait_for_run, run_id)
    if state["verdict"] != "passed":
        raise HarnessError(f"strict replay không passed: {state}")
    events = await asyncio.to_thread(harness.run_events, run_id)
    probe = probe_from_events(events)
    counters = probe.get("counters", {})
    if counters.get("item_created") != 1:
        raise HarnessError(f"probe item_created không bằng 1: {counters}")
    checks.append(HarnessCheck("strict-replay-passed", True, f"run {run_id} verdict=passed, probe item_created=1"))
    if CANARY_KEY in str(events):
        raise HarnessError("canary xuất hiện trong events")
    checks.append(HarnessCheck("canary-absent-events", True, "canary không có trong events/frames payload"))
    if ITEM_NAME not in str(probe):
        raise HarnessError("probe thiếu item_name của lần chạy")
    replay = {"run_id": run_id, "state": state}
    return checks, draft_state, replay
