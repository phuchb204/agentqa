import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from playwright.async_api import Page, async_playwright

from agentqa.agent.executor import ActionExecutionError, execute
from agentqa.agent.observation import observe
from agentqa.agent.policy import Policy
from agentqa.contracts import (
    AssertionResult,
    AssertionSpec,
    RunMetrics,
    RunTrace,
    RunVersions,
    StepResult,
    TestCase,
)

Checker = Callable[[Page, list[AssertionSpec]], Awaitable[list[AssertionResult]]]

APP_VERSION = "0.1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def run_case(
    case: TestCase,
    policy: Policy,
    *,
    base_url: str,
    headless: bool = True,
    checker: Checker,
) -> RunTrace:
    run_id = f"{case.name}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    started_at = _now()
    t0 = time.perf_counter()
    steps: list[StepResult] = []
    assertions: list[AssertionResult] = []
    history: list[str] = []
    input_tokens = output_tokens = llm_calls = 0
    status = "failed"
    error = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            if case.start_path.startswith("http"):
                start_url = case.start_path
            else:
                start_url = f"{base_url.rstrip('/')}/{case.start_path.lstrip('/')}"
            await page.goto(start_url)
            finished = False
            for index in range(case.max_steps):
                snapshot = await observe(page)
                result = await policy.decide(case.goal, snapshot, history)
                llm_calls += result.calls
                input_tokens += result.input_tokens
                output_tokens += result.output_tokens
                if result.action.type == "finish":
                    finished = True
                    break
                step_started = time.perf_counter()
                step_error = None
                try:
                    await execute(page, result.action)
                except ActionExecutionError as exc:
                    step_error = str(exc)
                steps.append(
                    StepResult(
                        index=index,
                        action=result.action,
                        ok=step_error is None,
                        error=step_error,
                        duration_ms=int((time.perf_counter() - step_started) * 1000),
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        observation_bytes=snapshot.size_bytes,
                    )
                )
                outcome = "ok" if step_error is None else f"error: {step_error}"
                history.append(
                    f"bước {index + 1}: {result.action.type} {result.action.target or ''} -> {outcome}"
                )
            assertions = await checker(page, case.assertions)
            passed = (
                finished
                and all(a.status == "passed" for a in assertions)
                and all(s.ok for s in steps)
            )
            status = "passed" if passed else "failed"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error = str(exc)
        finally:
            await browser.close()

    return RunTrace(
        run_id=run_id,
        case_name=case.name,
        status=status,
        started_at=started_at,
        finished_at=_now(),
        steps=steps,
        assertions=assertions,
        metrics=RunMetrics(
            llm_calls=llm_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_s=round(time.perf_counter() - t0, 3),
        ),
        versions=RunVersions(app=APP_VERSION, model=policy.model, prompt=policy.prompt_version),
        error=error,
    )
