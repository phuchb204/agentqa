from __future__ import annotations

import asyncio

import pytest

from agentqa.platform.supervisor import RuntimeConfig, SupervisorRuntime
from tests.support.faults import FakeExecutor, command_request

pytestmark = pytest.mark.asyncio

SESSION = "cancel-1"


async def test_cancel_requested_blocks_admission_then_effective(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)

    control = await env.controls.request(run_id=env.run_id, action="cancel", requested_by="tester")
    requested = await env.controls.latest(env.run_id)
    assert requested.effective_at is None

    rejected = await runtime.execute(command_request(env, session_key=SESSION))
    assert rejected.state == "rejected"
    assert rejected.evidence == ["control_cancelled"]

    result = await runtime.apply_control(control.id)
    assert result["effective"] is True
    effective = await env.controls.latest(env.run_id)
    assert effective.effective_at is not None
    assert effective.effective_reason == "barrier_applied"

    second = await runtime.execute(command_request(env, session_key=SESSION))
    assert second.state == "rejected"
    assert second.evidence == ["control_cancelled"]
    assert executor.calls == []


async def test_duplicate_control_request_returns_same_record(fault_env) -> None:
    env = fault_env
    first = await env.controls.request(run_id=env.run_id, action="pause", requested_by="tester")
    second = await env.controls.request(run_id=env.run_id, action="pause", requested_by="tester")
    assert first.id == second.id
    assert first.requested_at == second.requested_at


async def test_cancel_during_inflight_marks_unknown_within_bound(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor(delay=2.0)
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1", control_wait_seconds=0.3))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)
    request = command_request(env, session_key=SESSION)
    task = asyncio.create_task(runtime.execute(request))
    await asyncio.sleep(0.3)
    assert not task.done()
    control = await env.controls.request(run_id=env.run_id, action="cancel", requested_by="tester")

    result = await runtime.apply_control(control.id)
    assert result["uncertain_commands"] == [str(request.command_id)]

    receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == request.command_id]
    assert receipts[-1].state == "unknown"
    assert receipts[-1].reason == "cancel_bound_exceeded"

    final = await task
    assert final.state == "unknown"
    assert len(executor.calls) == 1


async def test_pause_effective_then_resume_allows_new_commands(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)

    pause = await env.controls.request(run_id=env.run_id, action="pause", requested_by="tester")
    rejected = await runtime.execute(command_request(env, session_key=SESSION))
    assert rejected.evidence == ["control_paused"]
    await runtime.apply_control(pause.id)

    resume = await env.controls.request(run_id=env.run_id, action="resume", requested_by="tester")
    accepted = await runtime.execute(command_request(env, session_key=SESSION))
    assert accepted.state == "settled"
    assert accepted.outcome == "succeeded"
    result = await runtime.apply_control(resume.id)
    assert result["effective"] is True
    assert len(executor.calls) == 1
