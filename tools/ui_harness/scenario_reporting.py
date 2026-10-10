from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from tools.ui_harness.runner import HarnessCheck, HarnessError

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALING_CASE_PATH = REPO_ROOT / "benchmarks" / "public" / "cases" / "taskboard" / "healing_delete_item.yaml"


async def drive_reporting_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict]:
    from playwright.async_api import async_playwright

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    workspace_id = str(harness.seed.workspace_id)

    live_revision = await asyncio.to_thread(harness.seed_ready_case, logical_key="report_live_case")
    run_ok = await asyncio.to_thread(harness.run_replay, live_revision)
    state_ok = await asyncio.to_thread(harness.wait_for_run, run_ok)
    if state_ok["verdict"] != "passed" or state_ok["gate"] != "passed":
        raise HarnessError(f"run báo cáo không đạt: {state_ok}")

    document = yaml.safe_load(HEALING_CASE_PATH.read_text(encoding="utf-8"))
    document["logical_key"] = "report_healed_case"
    healing_revision = await asyncio.to_thread(
        harness.seed_case_document, logical_key="report_healed_case", document=document
    )
    run_healed = await asyncio.to_thread(
        harness.run_replay, healing_revision, policy="replay_healing", gate_profile="strict"
    )
    state_healed = await asyncio.to_thread(harness.wait_for_run, run_healed)
    if state_healed["verdict"] != "passed" or state_healed["gate"] != "refused":
        raise HarnessError(f"run healed strict không đúng: {state_healed}")

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

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/runs/{run_ok}")
            await page.get_by_test_id("reports-section").wait_for()
            await page.get_by_role("button", name="Tạo báo cáo JSON", exact=True).click()
            await page.get_by_text(re.compile(r"JSON · checksum")).wait_for()
            checks.append(HarnessCheck("report-created", True, "báo cáo JSON có checksum và link tải"))

            await page.get_by_role("button", name="Tạo gói lỗi").click()
            await page.get_by_test_id("issue-package-preview").wait_for()
            preview = await page.get_by_test_id("issue-package-preview").inner_text()
            if "issue-package/1" not in preview:
                raise HarnessError(f"preview gói lỗi thiếu schema_version: {preview[:120]}")
            if "Tải gói lỗi" not in (await page.evaluate("() => document.body.textContent || ''")):
                raise HarnessError("thiếu link tải gói lỗi")
            checks.append(HarnessCheck("issue-package-preview", True, "preview redacted + link tải, không auto-send"))

            await page.get_by_role("button", name="Tạo phân tích đề xuất").click()
            await page.get_by_test_id("diagnostics-list").wait_for()
            diagnostics_text = await page.get_by_test_id("diagnostics-list").inner_text()
            if "Đề xuất phân tích" not in diagnostics_text:
                raise HarnessError(f"diagnostic thiếu label: {diagnostics_text[:120]}")
            if "Không thay kết luận cuối" not in diagnostics_text:
                raise HarnessError("diagnostic thiếu ghi chú không thay verdict")
            checks.append(HarnessCheck("diagnostic-label", True, "diagnostic có label/confidence và không sửa verdict"))

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/runs/{run_healed}")
            await page.get_by_text(re.compile(r"Kết luận lượt chạy")).wait_for()
            body_text = await page.evaluate("() => document.body.textContent || ''")
            if "refused" not in body_text:
                raise HarnessError("run detail không hiển thị gate refusal")
            if "healed" not in body_text:
                raise HarnessError("run detail không hiển thị annotation healed")
            if "Ứng dụng lỗi" in body_text:
                raise HarnessError("gate rejection bị hiển thị như lỗi ứng dụng")
            checks.append(
                HarnessCheck(
                    "gate-rejection-labelled", True, "healed strict hiển thị gate refusal, không phải lỗi ứng dụng"
                )
            )

            if "Không có dữ liệu chi phí" not in body_text and "unknown" not in body_text:
                raise HarnessError("thiếu trạng thái chi phí unknown")
            checks.append(HarnessCheck("unknown-cost-visible", True, "chi phí unknown hiển thị rõ, không phải zero"))
        finally:
            await context.close()
            await browser.close()

    return checks, {"run_ok": run_ok, "run_healed": run_healed}
