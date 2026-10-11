from __future__ import annotations

from typing import TYPE_CHECKING

from tools.ui_harness.runner import HarnessCheck, HarnessError

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness


def experiment_manifest() -> dict:
    return {
        "schema_version": "experiment-manifest/1",
        "experiment_id": "rq3-ui",
        "version": "1",
        "research_question": "rq3",
        "corpus": {"cases": ["exp_case"], "data_rows": []},
        "arms": [
            {
                "arm_id": "static_baseline",
                "mode": "replay",
                "policy": "replay_strict",
                "baseline": True,
                "plan_ref": "benchmarks/public/baselines/plans/taskboard/create_item_baseline.yaml",
            },
            {"arm_id": "llm_agent", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {"arm_id": "cascade_agent", "mode": "agent", "policy": "jev_cascade", "observation": "semantic"},
            {"arm_id": "strict_replay", "mode": "replay", "policy": "replay_strict"},
            {"arm_id": "healing_replay", "mode": "replay", "policy": "replay_healing", "healing": True},
        ],
        "samples": {"unit": "case_family", "confidence": 0.95, "repetitions": 1},
        "budgets": {
            "max_calls": 20,
            "max_cost_usd": 2.0,
            "routes": {"opencode_go": "deepseek-v4.1-flash", "opencode_zen": "jev-1.13-free"},
        },
        "analysis": {
            "primary_endpoints": ["oracle_task_success"],
            "comparisons": [["llm_agent", "static_baseline"]],
            "bootstrap_seed": 20261010,
            "bootstrap_replicates": 1000,
            "multiple_comparison": "holm",
        },
        "seeds": [20261010],
    }


async def drive_experiments_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict]:
    import asyncio

    from playwright.async_api import async_playwright

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    workspace_id = str(harness.seed.workspace_id)

    case_revision = await asyncio.to_thread(harness.seed_ready_case, logical_key="exp_case")
    harness.seeded_case_revision = case_revision
    revision_id = await asyncio.to_thread(
        harness.seed_experiment_revision, logical_key="rq3-ui", content=experiment_manifest()
    )
    summary = await asyncio.to_thread(harness.execute_experiment, revision_id)
    if summary["completed"] < 1 or summary["blocked"] < 1:
        raise HarnessError(f"execute experiment thiếu completed/blocked: {summary}")
    checks.append(
        HarnessCheck(
            "experiment-execute",
            True,
            f"attempt {summary['attempt_no']}: {summary['completed']} completed, {summary['blocked']} blocked",
        )
    )

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
            await page.get_by_role("link", name="Thực nghiệm").wait_for()

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/experiments")
            await page.get_by_test_id("experiments-list").wait_for()
            list_text = await page.get_by_test_id("experiments-list").inner_text()
            if "rq3-ui" not in list_text:
                raise HarnessError("danh sách experiments thiếu rq3-ui")
            checks.append(HarnessCheck("experiments-list", True, "danh sách revision hiển thị"))

            await page.get_by_role("link", name="Mở kết quả").first.click()
            await page.get_by_test_id("experiment-results").wait_for()
            arm_summary = await page.get_by_test_id("arm-summary").inner_text()
            for expected in ("static_baseline", "llm_agent", "blocked"):
                if expected not in arm_summary:
                    raise HarnessError(f"arm-summary thiếu {expected}: {arm_summary[:200]}")
            oracle_text = await page.get_by_test_id("oracle-uncertainty-static_baseline").inner_text()
            if "…" not in oracle_text:
                raise HarnessError(f"thiếu lower…upper cho oracle: {oracle_text}")
            checks.append(
                HarnessCheck("arm-summary-separated", True, "bảng arm tách product/oracle/gate, blocked hiển thị")
            )

            confounds = await page.get_by_test_id("confound-flags").inner_text()
            if "alias chưa xác minh" not in confounds or "cost basis" not in confounds:
                raise HarnessError("thiếu cờ nhiễu alias/cache/cost basis")
            checks.append(HarnessCheck("confound-flags", True, "cờ alias/cache/cost basis hiển thị"))

            await page.get_by_label("Lọc arm").select_option("static_baseline")
            rows = page.get_by_test_id("slot-table").locator("tbody tr")
            await rows.first.wait_for()
            row_count = await rows.count()
            if row_count != 1:
                raise HarnessError(f"filter arm trả {row_count} rows, mong đợi 1")
            checks.append(HarnessCheck("slot-filter", True, "lọc theo arm hoạt động"))

            await rows.first.click()
            detail = await page.get_by_test_id("slot-detail").inner_text()
            for expected in ("Sản phẩm:", "Oracle:", "Gate:"):
                if expected not in detail:
                    raise HarnessError(f"slot detail thiếu {expected}: {detail[:200]}")
            checks.append(
                HarnessCheck("slot-drilldown", True, "drill-down slot tách product/oracle/gate, unscorable rõ")
            )

            charts = await page.get_by_test_id("experiment-charts").inner_text()
            if "static_baseline" not in charts:
                raise HarnessError("charts thiếu arm")
            checks.append(HarnessCheck("experiment-charts", True, "biểu đồ oracle success từ metrics"))
        finally:
            await context.close()
            await browser.close()

    return checks, {"revision_id": revision_id, "summary": summary}
