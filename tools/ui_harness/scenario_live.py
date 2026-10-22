from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

from tools.ui_harness.runner import HarnessCheck, HarnessError, probe_from_events

if TYPE_CHECKING:
    from tools.ui_harness.runner import UiHarness

FRAME_STATUS_PATTERNS = (
    "Frame đã mask",
    "Không có frame",
    "Browser stream đã đóng",
    "Browser view không kết nối được",
)


async def drive_live_flow(harness: UiHarness) -> tuple[list[HarnessCheck], dict]:
    from playwright.async_api import async_playwright

    assert harness.seed is not None
    checks: list[HarnessCheck] = []
    revision_id = await asyncio.to_thread(harness.seed_ready_case)
    workspace_id = str(harness.seed.workspace_id)

    run_a = await asyncio.to_thread(harness.run_replay, revision_id)
    state_a = await asyncio.to_thread(harness.wait_for_run, run_a)
    if state_a["verdict"] != "passed":
        raise HarnessError(f"run A không passed: {state_a}")
    checks.append(HarnessCheck("strict-run-passed", True, f"run {run_a} passed"))

    await asyncio.to_thread(harness.pause_worker)
    run_c = await asyncio.to_thread(harness.run_replay, revision_id)

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

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/live/{run_c}")
            await page.get_by_text("Chưa có kết luận").wait_for()
            checks.append(HarnessCheck("live-verdict-not-final", True, "verdict active là 'Chưa có kết luận'"))

            await page.keyboard.press("Tab")
            focused = await page.evaluate("() => document.activeElement && document.activeElement.textContent")
            if not (focused and "Bỏ qua điều hướng" in str(focused)):
                raise HarnessError(f"keyboard focus sai: {focused!r}")
            checks.append(HarnessCheck("keyboard-focus-live", True, "Tab đầu tiên vào skip-link"))

            await page.get_by_role("button", name="Tạm dừng").click()
            await page.get_by_text(re.compile(r"Requested: 1")).wait_for()
            checks.append(HarnessCheck("control-requested", True, "control requested hiển thị trước effective"))

            await asyncio.to_thread(harness.resume_worker)
            frame_text = ""
            try:
                await page.wait_for_function(
                    "() => Array.from(document.querySelectorAll('[role=status]')).some("
                    "  (el) => /Frame đã mask|Không có frame|Browser stream đã đóng|"
                    "Browser view không kết nối được/.test(el.textContent || ''))",
                    timeout=15000,
                )
                frame_text = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('[role=status]'))"
                    ".map((el) => el.textContent).join(' | ')"
                )
            except Exception:
                frame_text = "timeout"
            if not any(pattern in frame_text for pattern in FRAME_STATUS_PATTERNS):
                raise HarnessError(f"browser-stream không trả typed status: {frame_text!r}")
            if "không kết nối được" in frame_text:
                raise HarnessError(f"browser-stream không kết nối được: {frame_text!r}")
            checks.append(HarnessCheck("browser-stream-typed", True, f"WS status: {frame_text[:140]}"))

            state_c = await asyncio.to_thread(harness.wait_for_run, run_c)
            if state_c["verdict"] == "passed":
                raise HarnessError(f"run C bị pause nhưng passed: {state_c}")
            await page.get_by_text(re.compile(r"Effective: [1-9]")).wait_for()
            checks.append(
                HarnessCheck("control-effective", True, f"effective xuất hiện sau khi supervisor áp dụng: {state_c}")
            )

            event_buttons = page.locator("ol button")
            count_before = await event_buttons.count()
            await page.reload()
            await page.get_by_text(re.compile(r"Timeline theo run_seq")).wait_for()
            await page.wait_for_timeout(1500)
            sequences = await page.locator("ol button").all_text_contents()
            parsed = [int(re.match(r"#(\d+)", text).group(1)) for text in sequences if re.match(r"#(\d+)", text)]
            if len(parsed) != len(set(parsed)):
                raise HarnessError(f"reconnect bị lặp event: {parsed}")
            checks.append(
                HarnessCheck(
                    "reconnect-dedupe", True, f"reload không lặp run_seq (before={count_before}, after={len(parsed)})"
                )
            )

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/runs/{run_a}")
            await page.get_by_text(re.compile(r"Kết luận lượt chạy")).wait_for()
            await page.get_by_text(re.compile(r"Đạt")).wait_for()
            usage_text = await page.evaluate("() => document.body.textContent || ''")
            if "Không có dữ liệu chi phí" not in usage_text and "0" not in usage_text:
                raise HarnessError("detail thiếu trạng thái chi phí")
            checks.append(HarnessCheck("run-detail-verdict", True, "detail hiển thị verdict/usage từ server"))

            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/compare?run_a={run_a}&run_b={run_c}")
            await page.get_by_text(re.compile(r"Khác biệt cấu hình")).wait_for()
            body_text = await page.evaluate("() => document.body.textContent || ''")
            config_index = body_text.find("Khác biệt cấu hình")
            metrics_index = body_text.find("Metrics")
            if config_index < 0 or metrics_index < 0 or config_index > metrics_index:
                raise HarnessError("compare không đặt config diff trước metrics")
            if "Không có dữ liệu chi phí" not in body_text and "Không có dữ liệu usage" not in body_text:
                raise HarnessError("compare thiếu trạng thái missingness của money/usage")
            checks.append(HarnessCheck("compare-config-first", True, "config diff hiển thị trước metrics"))

            await asyncio.to_thread(harness.pause_worker)
            t_submit = time.monotonic()
            long_revision = await asyncio.to_thread(
                harness.seed_ready_case, logical_key="live_case_long", settle_seconds=30
            )
            run_d = await asyncio.to_thread(harness.run_replay, long_revision)
            await page.goto(f"{harness.web_base_url}/w/{workspace_id}/live/{run_d}")
            t_goto = time.monotonic()
            await page.wait_for_function(
                "() => Array.from(document.querySelectorAll('[role=status]')).some("
                "  (el) => /Frame đã mask|Không có frame|Browser stream đã đóng|"
                "Browser view không kết nối được/.test(el.textContent || ''))",
                timeout=15000,
            )
            await asyncio.to_thread(harness.resume_worker)
            t_resume = time.monotonic()
            deadline = time.monotonic() + 120.0
            frame_src: str | None = None
            frame_run_status = ""
            last_status = ""
            reloads = 0
            polls = 0
            saw_statuses: list[str] = []
            terminal_since = 0.0
            while time.monotonic() < deadline:
                polls += 1
                try:
                    candidate = await page.get_attribute("img", "src")
                except Exception:
                    candidate = None
                if candidate and candidate.startswith("data:image/png;base64,iVBOR"):
                    frame_src = candidate
                    try:
                        frame_run_status = str((await asyncio.to_thread(harness.peek_run, run_d)).get("status", ""))
                    except Exception:
                        frame_run_status = "peek_failed"
                    break
                last_status = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('[role=status]'))"
                    ".map((el) => el.textContent).join(' | ')"
                )
                short = last_status[:60]
                if not saw_statuses or saw_statuses[-1] != short:
                    saw_statuses.append(short)
                try:
                    run_status = str((await asyncio.to_thread(harness.peek_run, run_d)).get("status", ""))
                except Exception:
                    run_status = "peek_failed"
                if run_status in ("succeeded", "failed", "cancelled", "error", "inconclusive"):
                    if terminal_since == 0.0:
                        terminal_since = time.monotonic()
                    if time.monotonic() - terminal_since > 10.0:
                        break
                    await page.wait_for_timeout(500)
                elif "Browser stream đã đóng" in last_status and reloads < 2:
                    reloads += 1
                    await page.reload()
                    await page.wait_for_timeout(1000)
                else:
                    await page.wait_for_timeout(500)
            if not frame_src:
                raise HarnessError(
                    "không nhận được frame masked (img PNG qua WS trong lúc run active): "
                    f"status={last_status!r} reloads={reloads} "
                    f"t_submit_goto={t_goto - t_submit:.1f}s t_goto_resume={t_resume - t_goto:.1f}s "
                    f"polls={polls} status_chuyen={saw_statuses}"
                )
            checks.append(
                HarnessCheck(
                    "browser-frame-masked",
                    True,
                    f"nhận frame PNG masked qua WS (run {frame_run_status} lúc nhận)",
                )
            )
            await page.wait_for_timeout(300)
            await page.close()
            state_d = await asyncio.to_thread(harness.wait_for_run, run_d)
            if state_d["status"] not in ("succeeded", "failed", "cancelled", "error", "inconclusive"):
                raise HarnessError(f"tab close dừng engine: {state_d}")
            events_d = await asyncio.to_thread(harness.run_events, run_d)
            counters_d = probe_from_events(events_d).get("counters", {})
            if counters_d.get("item_created", 0) > 1:
                raise HarnessError(f"tab close gây side effect trùng: {counters_d}")
            checks.append(
                HarnessCheck(
                    "tab-close-engine-continues",
                    True,
                    f"run {run_d} vẫn tới terminal sau khi đóng tab: {state_d['status']}/{state_d['verdict']}",
                )
            )

            run_e = await asyncio.to_thread(harness.run_replay, revision_id)
            state_e = await asyncio.to_thread(harness.wait_for_run, run_e)
            if state_e["verdict"] != "passed":
                raise HarnessError(f"run sau fault không passed: {state_e}")
            events_e = await asyncio.to_thread(harness.run_events, run_e)
            counters_e = probe_from_events(events_e).get("counters", {})
            if counters_e.get("item_created") != 1:
                raise HarnessError(f"probe sau fault không bằng 1: {counters_e}")
            checks.append(HarnessCheck("post-fault-run-passed", True, f"run {run_e} passed sau fault UI"))

            page2 = await context.new_page()
            await page2.goto(f"{harness.web_base_url}/w/{workspace_id}/runs")
            await page2.get_by_text(re.compile(r"Lượt chạy")).first.wait_for()
            cookies = await context.cookies()
            session_cookie = next((item["value"] for item in cookies if item["name"] == "agentqa_session"), None)
            if session_cookie is None:
                raise HarnessError("không tìm thấy session cookie để revoke")
            await asyncio.to_thread(harness.revoke_session, session_cookie)
            await page2.reload()
            await page2.get_by_text("Đăng nhập AgentQA").wait_for()
            if not await asyncio.to_thread(harness.workspace_requires_auth):
                raise HarnessError("stale token vẫn truy cập được API")
            checks.append(HarnessCheck("stale-token-acl", True, "session revoke đóng UI và API trả 401"))
            await page2.close()
        except Exception as error:
            try:
                await page.screenshot(path=str(harness.workspace_root / "failure.png"), full_page=True)
                (harness.workspace_root / "failure.html").write_text(await page.content(), encoding="utf-8")
                (harness.workspace_root / "console.log").write_text("\n".join(console_lines), encoding="utf-8")
            except Exception:
                pass
            raise HarnessError(f"{error}") from error
        finally:
            await context.close()
            await browser.close()

    return checks, {"run_a": str(run_a), "run_c": str(run_c)}
