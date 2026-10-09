from __future__ import annotations

import asyncio

import pytest

from agentqa.platform.queue import JobQueue, QueueUnavailable
from agentqa.platform.storage.database import create_engine, create_session_factory
from agentqa.platform.supervisor import RuntimeConfig, SupervisorRuntime
from tests.support.faults import FakeExecutor, command_request, scoped_rows

pytestmark = pytest.mark.asyncio

SESSION = "lease-1"


async def test_claim_lock_order_epoch_and_slot_reservation(fault_env) -> None:
    env = fault_env
    first = await env.queue.claim("worker-1", lease_seconds=30)
    assert first is not None
    assert first.epoch == 1
    assert (await env.queue.slot_state())["reserved"] == 1

    blocked = await env.queue.claim("worker-2")
    assert blocked is None

    assert await env.queue.heartbeat(first.lease_id) is True
    await env.queue.release(first.lease_id, job_state="queued")
    assert (await env.queue.slot_state())["reserved"] == 0

    second = await env.queue.claim("worker-2", lease_seconds=30)
    assert second is not None
    assert second.job_id == first.job_id
    assert second.epoch == 2
    await env.queue.release(second.lease_id)


async def test_two_workers_claim_distinct_jobs(fault_env) -> None:
    env = fault_env
    from tests.support.postgres import seed_job

    second_job = await seed_job(
        env.engines,
        principal_id=env.user_id,
        workspace_id=env.workspace_id,
        run_id=env.run_id,
        execution_id=env.execution_id,
    )
    first = await env.queue.claim("worker-1")
    assert first is not None
    assert first.job_id == env.job_id
    await env.queue.release(first.lease_id)
    second = await env.queue.claim("worker-2")
    assert second is not None
    assert second.job_id == second_job
    await env.queue.release(second.lease_id)


async def test_heartbeat_expiry_quarantines_and_blocks_requeue(fault_env) -> None:
    env = fault_env
    claim = await env.queue.claim("worker-1", lease_seconds=1)
    assert claim is not None
    await asyncio.sleep(1.3)
    assert await env.queue.heartbeat(claim.lease_id) is False
    await env.queue.quarantine(claim.lease_id, reason="lease_lost")
    rows = scoped_rows(
        env.worker_dsn,
        env.workspace_id,
        env.user_id,
        "SELECT state, payload->>'quarantine_reason' FROM jobs WHERE id = %s",
        (env.job_id,),
    )
    assert rows[0][0] == "quarantined"
    assert rows[0][1] == "lease_lost"
    assert (await env.queue.slot_state())["reserved"] == 0
    assert await env.queue.claim("worker-2", lease_seconds=5) is None


async def test_db_unavailable_raises_and_stops_admission(fault_env) -> None:
    env = fault_env
    engine = create_engine(
        "postgresql+psycopg://agentqa_worker:agentqa_test_local_only@127.0.0.1:59999/khong_ton_tai?connect_timeout=2",
        pool_size=1,
        max_overflow=0,
    )
    queue = JobQueue(create_session_factory(engine), workspace_id=env.workspace_id, principal_id=env.user_id)
    try:
        with pytest.raises(QueueUnavailable):
            await queue.claim("worker-1")
        with pytest.raises(QueueUnavailable):
            await queue.admission_available()
    finally:
        await engine.dispose()


async def test_heartbeat_survives_blocking_work(fault_env) -> None:
    env = fault_env
    executor = FakeExecutor(delay=1.2)
    runtime = SupervisorRuntime(env.journal, executor, RuntimeConfig("sup-1", lease_seconds=1.0))
    await runtime.open_session(run_id=env.run_id, attempt_id=env.attempt_id, session_key=SESSION, fence_epoch=1)
    request = command_request(env, session_key=SESSION)
    task = asyncio.create_task(runtime.execute(request))
    renewals = 0
    while not task.done():
        assert await runtime.heartbeat(SESSION) is True
        renewals += 1
        await asyncio.sleep(0.3)
    final = await task
    assert final.state == "settled"
    assert renewals >= 2
    assert len(executor.calls) == 1
