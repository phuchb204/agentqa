from __future__ import annotations

import pytest

from agentqa.platform.supervisor import RuntimeConfig, SupervisorRuntime
from tests.support.faults import FakeExecutor, command_request

pytestmark = pytest.mark.asyncio

SESSION = "recovery-1"


async def test_reconcile_marks_unknown_and_quarantines_without_replay(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)

    request = command_request(env, session_key=SESSION)
    await env.journal.prepare(request)
    admitted = await env.journal.admit(
        request.command_id, fence_epoch=1, control_revision=0, expected_observation_version=1
    )
    assert admitted.state == "accepted"
    await env.journal.mark_dispatched(request.command_id, fence_epoch=1)

    report = await env.recovery.reconcile_attempt(env.attempt_id)
    assert request.command_id in report.unknown_command_ids
    assert SESSION in report.quarantined_sessions
    assert executor.calls == []

    receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == request.command_id]
    assert [r.state for r in receipts] == ["accepted", "dispatched", "unknown"]
    assert receipts[-1].reason == "owner_lost_reconciliation"

    session = await env.journal.session_view(SESSION)
    assert session is not None
    assert session["state"] == "quarantined"
    assert session["closed_reason"] == "owner_lost"


async def test_retry_requires_fixture_reset_after_unknown(fault_env) -> None:
    env = fault_env
    request = command_request(env, session_key="recovery-retry")
    await env.journal.open_session(
        run_id=env.run_id, attempt_id=env.attempt_id, session_key="recovery-retry", fence_epoch=1
    )
    await env.journal.prepare(request)
    await env.journal.admit(request.command_id, fence_epoch=1, control_revision=0, expected_observation_version=1)
    await env.journal.mark_dispatched(request.command_id, fence_epoch=1)
    await env.journal.mark_unknown(request.command_id, fence_epoch=1, reason="owner_lost_reconciliation")

    blocked = await env.recovery.retry_decision(env.attempt_id, fixture_reset_ok=False)
    assert blocked.allowed is False
    assert "fixture reset" in blocked.reason

    allowed = await env.recovery.retry_decision(env.attempt_id, fixture_reset_ok=True)
    assert allowed.allowed is True


async def test_reconcile_does_not_touch_settled_commands(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(
        run_id=env.run_id, attempt_id=env.attempt_id, session_key="recovery-settled", fence_epoch=1
    )
    settled = await runtime.execute(command_request(env, session_key="recovery-settled"))
    assert settled.state == "settled"

    report = await env.recovery.reconcile_attempt(env.attempt_id)
    assert settled.command_id not in report.unknown_command_ids
    receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == settled.command_id]
    assert receipts[-1].state == "settled"


async def test_quarantined_job_not_returned_to_queue(fault_env) -> None:
    env = fault_env
    claim = await env.queue.claim("worker-1", lease_seconds=30)
    assert claim is not None
    await env.queue.quarantine(claim.lease_id, reason="supervisor_lost")
    rows = env.queue
    assert await rows.claim("worker-2", lease_seconds=5) is None
