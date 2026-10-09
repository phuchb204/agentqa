from __future__ import annotations

import pytest

from agentqa.platform.supervisor import JournalUnavailable, RuntimeConfig, SupervisorRuntime
from agentqa.platform.supervisor.journal import StaleFence
from tests.support.faults import FakeExecutor, command_request

pytestmark = pytest.mark.asyncio

SESSION = "journal-1"


async def test_receipt_lifecycle_duplicate_returns_same_receipt(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)
    request = command_request(env, session_key=SESSION, operation="navigate")
    final = await runtime.execute(request)
    assert final.state == "settled"
    assert final.outcome == "succeeded"
    receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == request.command_id]
    assert [r.state for r in receipts] == ["accepted", "dispatched", "settled"]
    assert receipts[0].input_digest and receipts[0].input_digest == receipts[-1].input_digest

    duplicate = await runtime.execute(request)
    assert duplicate.state == "settled"
    assert duplicate.outcome == "succeeded"
    assert len(executor.calls) == 1
    assert len([r for r in await env.journal.receipts(env.attempt_id) if r.command_id == request.command_id]) == 3


async def test_rejected_commands_recorded_without_dispatch(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)

    stale = command_request(env, session_key=SESSION, expected_observation_version=7)
    receipt = await runtime.execute(stale)
    assert receipt.state == "rejected"
    assert "scene_stale" in receipt.evidence

    control = await env.controls.request(run_id=env.run_id, action="pause", requested_by="tester")
    paused = command_request(env, session_key=SESSION)
    receipt = await runtime.execute(paused)
    assert receipt.state == "rejected"
    assert receipt.evidence == ["control_paused"]
    duplicate = await runtime.execute(paused)
    assert duplicate.state == "rejected"
    assert duplicate.command_id == paused.command_id

    await env.controls.mark_effective(control.id, reason="barrier")
    assert executor.calls == []


async def test_stale_fence_cannot_write_terminal(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1"))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)
    request = command_request(env, session_key=SESSION)
    final = await runtime.execute(request)
    assert final.state == "settled"

    with pytest.raises(StaleFence):
        await env.journal.settle(
            request.command_id,
            fence_epoch=2,
            outcome="succeeded",
            evidence=["stale_attempt"],
        )
    receipts = [r for r in await env.journal.receipts(env.attempt_id) if r.command_id == request.command_id]
    assert receipts[-1].state == "settled"
    assert "stale_attempt" not in receipts[-1].evidence


class BrokenJournal:
    def __init__(self, journal) -> None:
        self._journal = journal

    def __getattr__(self, name: str):
        raise JournalUnavailable("db down")


async def test_db_unavailable_stops_admission_without_side_effect(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor()
    runtime = SupervisorRuntime(BrokenJournal(env.journal), executor, RuntimeConfig("sup-1"))
    request = command_request(env, session_key="db-down")
    receipt = await runtime.execute(request)
    assert receipt.state == "rejected"
    assert receipt.evidence == ["db_unavailable"]
    assert executor.calls == []
    assert await env.journal.receipts(env.attempt_id) == []
