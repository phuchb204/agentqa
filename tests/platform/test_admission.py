from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.support.postgres import scoped_transaction, seed_execution, seed_job, seed_run, seed_workspace

from agentqa.platform.queue import JobQueue
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


def _resource_payload(keys: list[tuple[str, str]]) -> dict:
    return {"resource_keys": [{"scope": scope, "key": key} for scope, key in keys]}


async def _seed_jobs(engines, *, count: int, keys: list[tuple[str, str]]) -> tuple:
    user_id, workspace_id = await seed_workspace(engines, label=f"adm-{uuid4().hex[:8]}")
    run_ids = []
    job_ids = []
    for index in range(count):
        run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id)
        execution_id = await seed_execution(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            logical_key=f"case-{index}",
        )
        job_id = await seed_job(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            execution_id=execution_id,
            payload=_resource_payload(keys),
        )
        run_ids.append(run_id)
        job_ids.append(job_id)
    return user_id, workspace_id, run_ids, job_ids


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


async def test_provider_reference_capacity_is_global(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _run_id, _job_ids = await _seed_jobs(
        engines, count=2, keys=[("workspace", "ws-shared"), ("provider", "opencode_go")]
    )
    capacities = {"provider": 1, "workspace": 5}
    first_queue = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)
    second_queue = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)

    first = await first_queue.claim("worker-1")
    assert first is not None
    assert {key.scope for key in first.resource_keys} == {"workspace", "provider"}
    blocked = await second_queue.claim("worker-2")
    assert blocked is None
    assert (
        await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_go") == 1
    )

    await first_queue.release(first.lease_id)
    assert (
        await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope="provider", key="opencode_go") == 0
    )
    second = await second_queue.claim("worker-2")
    assert second is not None
    assert second.resource_keys == first.resource_keys
    await second_queue.release(second.lease_id)


async def test_workspace_capacity_is_enforced(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _run_id, _job_ids = await _seed_jobs(engines, count=2, keys=[("workspace", "ws-only")])
    capacities = {"workspace": 1}
    first = await _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities).claim("worker-1")
    assert first is not None
    blocked = await _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities).claim("worker-2")
    assert blocked is None
    await _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities).release(first.lease_id)
    second = await _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities).claim("worker-2")
    assert second is not None
    await _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities).release(second.lease_id)


async def test_concurrent_claims_single_winner(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _run_id, job_ids = await _seed_jobs(engines, count=1, keys=[("workspace", "ws-race")])
    queue_a = _queue(engines, workspace_id=workspace_id, user_id=user_id)
    queue_b = _queue(engines, workspace_id=workspace_id, user_id=user_id)
    results = await asyncio.gather(queue_a.claim("worker-a"), queue_b.claim("worker-b"))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].job_id == job_ids[0]
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        leases = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.worker_leases)
                .where(tables.worker_leases.c.released_at.is_(None))
            )
        ).scalar_one()
    assert leases == 1
    await queue_a.release(winners[0].lease_id)


async def test_stale_lease_quarantine_releases_keys(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _run_id, _job_ids = await _seed_jobs(
        engines, count=1, keys=[("workspace", "ws-stale"), ("provider", "opencode_zen")]
    )
    capacities = {"provider": 1}
    queue = _queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities)
    claim = await queue.claim("worker-1", lease_seconds=1)
    assert claim is not None
    await asyncio.sleep(1.3)
    assert await queue.heartbeat(claim.lease_id) is False
    await queue.quarantine(claim.lease_id, reason="lease_lost")
    for scope, key in (("workspace", "ws-stale"), ("provider", "opencode_zen")):
        assert await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope=scope, key=key) == 0
    assert await queue.claim("worker-2", lease_seconds=5) is None


async def test_multi_key_concurrency_respects_all_capacities(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, _run_id, _job_ids = await _seed_jobs(
        engines, count=6, keys=[("workspace", "ws-multi"), ("browser", "chromium")]
    )
    capacities = {"workspace": 3, "browser": 3}
    queues = [_queue(engines, workspace_id=workspace_id, user_id=user_id, capacities=capacities) for _ in range(6)]
    results = await asyncio.wait_for(
        asyncio.gather(*(queue.claim(f"worker-{index}") for index, queue in enumerate(queues))),
        timeout=30,
    )
    winners = [result for result in results if result is not None]
    assert len(winners) == 3
    for scope, key in (("workspace", "ws-multi"), ("browser", "chromium")):
        assert await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope=scope, key=key) == len(
            winners
        )
    for index, result in enumerate(results):
        if result is not None:
            await queues[index].release(result.lease_id)
    for scope, key in (("workspace", "ws-multi"), ("browser", "chromium")):
        assert await _reserved(engines, workspace_id=workspace_id, user_id=user_id, scope=scope, key=key) == 0
