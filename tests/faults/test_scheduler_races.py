from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa

from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.service import RunService
from agentqa.platform.scheduler import SchedulerService
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER
from tests.support.platform import service_case_revision, service_suite_revision, service_workspace, suite_content
from tests.support.postgres import scoped_transaction, seed_execution, seed_job, seed_run, seed_workspace

pytestmark = pytest.mark.asyncio


async def _seed_race_env(engines, *, count: int, keys: list[tuple[str, str]]) -> tuple:
    user_id, workspace_id = await seed_workspace(engines, label=f"race-{uuid4().hex[:8]}")
    job_ids: list = []
    for index in range(count):
        run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id)
        execution_id = await seed_execution(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            logical_key=f"race-{index}",
        )
        job_id = await seed_job(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            execution_id=execution_id,
            payload={"resource_keys": [{"scope": scope, "key": key} for scope, key in keys]},
        )
        job_ids.append(job_id)
    return user_id, workspace_id, job_ids


def _queue(engines, *, workspace_id, user_id, capacities=None) -> JobQueue:
    return JobQueue(
        create_session_factory(engines[ROLE_WORKER]),
        workspace_id=workspace_id,
        principal_id=user_id,
        resource_capacities=capacities,
    )


async def _reserved(engines, *, workspace_id, user_id, scope: str, key: str) -> int:
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        value = (
            await session.execute(
                sa.select(tables.resource_slots.c.reserved).where(
                    tables.resource_slots.c.scope == scope,
                    tables.resource_slots.c.resource_key == key,
                )
            )
        ).scalar_one_or_none()
        return int(value or 0)


async def test_duplicate_claims_do_not_exceed_global_limit(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _job_ids = await _seed_race_env(engines, count=3, keys=[("provider", "opencode_go")])
    capacities = {"provider": 2}
    queues = [_queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities) for _ in range(4)]
    results = await asyncio.wait_for(
        asyncio.gather(*(queue.claim(f"race-worker-{index}") for index, queue in enumerate(queues))),
        timeout=30,
    )
    winners = [result for result in results if result is not None]
    assert len(winners) == 2
    assert (
        await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_go") == 2
    )
    for index, result in enumerate(results):
        if result is not None:
            await queues[index].release(result.lease_id)
    assert (
        await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_go") == 0
    )


async def test_stale_lease_release_is_noop_after_new_epoch(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, job_ids = await _seed_race_env(engines, count=1, keys=[("workspace", "ws-epoch")])
    capacities = {"workspace": 1}
    queue = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)
    first = await queue.claim("worker-1")
    assert first is not None
    await queue.release(first.lease_id, job_state="queued")
    second = await queue.claim("worker-2")
    assert second is not None
    assert second.job_id == job_ids[0]
    assert second.epoch > first.epoch
    await queue.release(first.lease_id)
    assert await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="workspace", key="ws-epoch") == 1
    await queue.release(second.lease_id)
    assert await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="workspace", key="ws-epoch") == 0


async def test_scheduler_claim_race_creates_single_run_and_single_admission(role_engines, test_db) -> None:
    from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile

    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.local(),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API), ROLE_WORKER: test_db.dsn(ROLE_WORKER)},
    )
    try:
        await _scheduler_claim_race(runtime, role_engines)
    finally:
        await runtime.aclose()


async def _scheduler_claim_race(runtime, role_engines) -> None:
    user_id, username, workspace_id = await service_workspace(runtime)
    case = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="race_case"
    )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="race_suite",
        content=suite_content("race_suite", case_refs=[{"logical_key": "race_case", "revision_no": case.revision_no}]),
    )
    engine = runtime.engines[ROLE_WORKER]
    early = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    schedulers = [SchedulerService(engine, run_service=RunService(engine)) for _ in range(3)]
    schedule_id = await schedulers[0].create_schedule(
        workspace_id=workspace_id, principal_id=user_id, logical_key="race_schedule"
    )
    await schedulers[0].add_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        schedule_id=schedule_id,
        content={
            "schema_version": "schedule/1",
            "logical_key": "race_schedule",
            "suite_revision_id": str(suite.revision_id),
            "timezone": "UTC",
            "hour": 8,
            "minute": 0,
            "days_of_week": [],
            "overlap": "skip",
        },
    )
    await schedulers[0].materialize_due(workspace_id=workspace_id, principal_id=user_id, now=early)
    due = datetime(2026, 6, 15, 8, 5, tzinfo=UTC)
    batches = await asyncio.wait_for(
        asyncio.gather(
            *(
                scheduler.claim_due(
                    workspace_id=workspace_id, principal_id=user_id, worker_id=f"race-sched-{index}", now=due
                )
                for index, scheduler in enumerate(schedulers)
            )
        ),
        timeout=30,
    )
    winners = [occurrence for batch in batches for occurrence in batch]
    assert len(winners) == 1
    async with scoped_transaction(engine, principal_id=user_id, workspace_id=workspace_id) as session:
        run_count = (await session.execute(sa.select(sa.func.count()).select_from(tables.runs))).scalar_one()
        claimed_occurrences = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.schedule_occurrences)
                .where(tables.schedule_occurrences.c.state == "claimed")
            )
        ).scalar_one()
    assert run_count == 1
    assert claimed_occurrences == 1

    queue = JobQueue(
        create_session_factory(engine),
        workspace_id=workspace_id,
        principal_id=user_id,
        resource_capacities={"workspace": 1},
    )
    claim = await queue.claim("race-worker")
    assert claim is not None
    assert claim.run_id == winners[0].run_id
    duplicate = await queue.claim("race-worker-2")
    assert duplicate is None
    async with scoped_transaction(engine, principal_id=user_id, workspace_id=workspace_id) as session:
        active_leases = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.worker_leases)
                .where(tables.worker_leases.c.released_at.is_(None))
            )
        ).scalar_one()
        claimed_jobs = (
            await session.execute(
                sa.select(sa.func.count()).select_from(tables.jobs).where(tables.jobs.c.state == "claimed")
            )
        ).scalar_one()
    assert active_leases == 1
    assert claimed_jobs == 1
    await queue.release(claim.lease_id)


async def test_release_and_claim_race_keeps_reserved_bounded(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _job_ids = await _seed_race_env(engines, count=2, keys=[("provider", "opencode_zen")])
    capacities = {"provider": 1}
    queue_a = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)
    queue_b = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)
    first = await queue_a.claim("worker-a")
    assert first is not None
    release_task = asyncio.create_task(queue_a.release(first.lease_id))
    claim_task = asyncio.create_task(queue_b.claim("worker-b"))
    await asyncio.wait_for(asyncio.gather(release_task, claim_task), timeout=30)
    second = claim_task.result()
    reserved = await _reserved(
        engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_zen"
    )
    if second is not None:
        assert reserved == 1
        await queue_b.release(second.lease_id)
    else:
        assert reserved == 0
    assert (
        await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_zen") == 0
    )
