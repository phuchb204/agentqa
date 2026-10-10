from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from tools.ui_harness.runner import HarnessCheck, HarnessError

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness

REPO_ROOT = Path(__file__).resolve().parents[2]
CASE_PATH = REPO_ROOT / "benchmarks" / "public" / "cases" / "taskboard" / "healing_delete_item.yaml"
ITEM_NAME = "Việc healing UI"


async def drive_healing_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict]:
    from playwright.async_api import async_playwright
    from tests.support.healing import synthetic_profile

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    harness.healing_profile = synthetic_profile()
    workspace_id = str(harness.seed.workspace_id)

    document = yaml.safe_load(CASE_PATH.read_text(encoding="utf-8"))
    document["logical_key"] = "healing_ui_case"
    revision_id = await asyncio.to_thread(harness.seed_case_document, logical_key="healing_ui_case", document=document)
    _revision_id, case_id = await asyncio.to_thread(harness.latest_case_revision, "healing_ui_case")

    run_allow = await asyncio.to_thread(
        harness.run_replay, revision_id, policy="replay_healing", gate_profile="allow_healing"
    )
    state_allow = await asyncio.to_thread(harness.wait_for_run, run_allow)
    if state_allow["verdict"] != "passed" or state_allow["gate"] != "passed":
        raise HarnessError(f"allow_healing run không đạt: {state_allow}")
    if "healed" not in state_allow["reasons"]:
        raise HarnessError(f"run thiếu annotation healed: {state_allow}")
    checks.append(HarnessCheck("healing-allow-gate", True, f"run {run_allow} passed với healed"))

    run_strict = await asyncio.to_thread(
        harness.run_replay, revision_id, policy="replay_healing", gate_profile="strict"
    )
    state_strict = await asyncio.to_thread(harness.wait_for_run, run_strict)
    if state_strict["verdict"] != "passed" or state_strict["gate"] != "refused":
        raise HarnessError(f"strict run không từ chối healed: {state_strict}")
    if "business_failure" in state_strict["reasons"]:
        raise HarnessError(f"gate rejection bị ghi thành business failure: {state_strict}")
    checks.append(HarnessCheck("healing-strict-gate", True, "strict từ chối healed nhưng verdict passed"))

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
            await page.get_by_role("link", name="Lượt chạy").wait_for()

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/runs/{run_allow}")
            await page.get_by_test_id("healing-section").wait_for()
            section_text = await page.get_by_test_id("healing-section").inner_text()
            if "Xoá việc" not in section_text or "Xoá" not in section_text:
                raise HarnessError(f"healing diff thiếu target gốc/candidate thực tế: {section_text!r}")
            if "Guard checks" not in section_text:
                raise HarnessError(f"healing diff thiếu guard checks: {section_text!r}")
            if "Source run" not in section_text:
                raise HarnessError(f"healing diff thiếu source run: {section_text!r}")
            checks.append(HarnessCheck("healing-diff-visible", True, "target gốc/candidate/guard/source hiển thị"))

            apply_button = page.get_by_role("button", name="Tạo bản chỉnh sửa với locator đề xuất")
            await apply_button.click()
            await page.get_by_text("Đã lưu đề xuất vào bản chỉnh sửa").wait_for()
            checks.append(HarnessCheck("healing-apply-draft", True, "đề xuất được lưu vào draft, không auto-promote"))

            draft_version = await asyncio.to_thread(harness.case_draft_version, case_id)
            if draft_version is None:
                raise HarnessError("draft chưa được tạo sau apply")
            ready_count = await asyncio.to_thread(harness.ready_case_revision_count, "healing_ui_case")
            if ready_count != 1:
                raise HarnessError(f"ready revision bị thay đổi sau run: {ready_count}")
            checks.append(
                HarnessCheck(
                    "healing-ready-unchanged",
                    True,
                    f"ready revision vẫn 1, draft edit_version={draft_version}",
                )
            )
        finally:
            await context.close()
            await browser.close()

    return checks, {"run_allow": run_allow, "run_strict": run_strict}
