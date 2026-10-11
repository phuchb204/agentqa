from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from infra.workloads.common import WorkloadContext

TOTAL_EXECUTIONS = 32
WORKER_COUNT = 6
FAKE_MODEL_LATENCY_SECONDS = 0.25


async def _reserved_now(engines: dict[str, Any], workspace_id: UUID, principal_id: UUID) -> int:
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_WORKER
    from agentqa.platform.storage.scope import set_scope
    from agentqa.platform.storage.tables import resource_slots

    factory = create_session_factory(engines[ROLE_WORKER])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
        value = (
            await session.execute(
                sa.select(sa.func.coalesce(sa.func.sum(resource_slots.c.reserved), 0)).where(
                    resource_slots.c.workspace_id == workspace_id
                )
            )
        ).scalar_one()
        return int(value)


async def _queued_count(engines: dict[str, Any], workspace_id: UUID, principal_id: UUID) -> int:
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_WORKER
    from agentqa.platform.storage.scope import set_scope
    from agentqa.platform.storage.tables import jobs

    factory = create_session_factory(engines[ROLE_WORKER])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
        value = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(jobs)
                .where(jobs.c.workspace_id == workspace_id, jobs.c.state == "queued")
            )
        ).scalar_one()
        return int(value)


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.postgres import seed_execution, seed_job, seed_run, seed_workspace

    from agentqa.platform.events.service import EventService
    from agentqa.platform.queue.leases import JobQueue
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_WORKER
    from agentqa.platform.storage.scope import set_scope
    from agentqa.platform.storage.tables import executions, jobs, worker_leases

    engines = ctx.engines
    user_id, workspace_id = await seed_workspace(engines, label="w2-shared")
    run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id, status="queued")
    for index in range(TOTAL_EXECUTIONS):
        execution_id = await seed_execution(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            logical_key=f"w2-case-{index:02d}",
        )
        await seed_job(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            execution_id=execution_id,
            payload={"resource_keys": [{"scope": "workspace", "key": str(workspace_id)}]},
        )

    queue = JobQueue(
        create_session_factory(engines[ROLE_WORKER]),
        workspace_id=workspace_id,
        principal_id=user_id,
        slot_capacity=4,
    )
    events_service = EventService(engines[ROLE_WORKER])
    peak_reserved = 0
    monitor_stop = asyncio.Event()

    async def monitor() -> None:
        nonlocal peak_reserved
        while not monitor_stop.is_set():
            try:
                current = await _reserved_now(engines, workspace_id, user_id)
            except Exception:
                current = 0
            peak_reserved = max(peak_reserved, current)
            try:
                await asyncio.wait_for(monitor_stop.wait(), timeout=0.02)
            except TimeoutError:
                continue

    async def settle(claim) -> None:
        factory = create_session_factory(engines[ROLE_WORKER])
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
            logical_key = (
                await session.execute(sa.select(executions.c.logical_key).where(executions.c.id == claim.execution_id))
            ).scalar_one()
            await session.execute(
                sa.update(executions)
                .where(executions.c.id == claim.execution_id)
                .values(status="succeeded", verdict="passed")
            )
            await events_service.append(
                session,
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="w2.completed",
                actor="w2-worker",
                execution_id=claim.execution_id,
                payload={"namespace": logical_key, "logical_key": logical_key},
            )

    async def worker(worker_name: str) -> int:
        done = 0
        while True:
            claim = await queue.claim(worker_name, lease_seconds=60)
            if claim is None:
                if await _queued_count(engines, workspace_id, user_id) == 0:
                    return done
                await asyncio.sleep(0.05)
                continue
            await asyncio.sleep(FAKE_MODEL_LATENCY_SECONDS)
            await queue.release(claim.lease_id, job_state="succeeded")
            await settle(claim)
            done += 1

    started = time.monotonic()
    monitor_task = asyncio.create_task(monitor())
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(worker(f"w2-worker-{index}") for index in range(WORKER_COUNT))),
            timeout=120,
        )
    finally:
        monitor_stop.set()
        await monitor_task
    wall_seconds = time.monotonic() - started

    factory = create_session_factory(engines[ROLE_WORKER])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
        succeeded = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(executions)
                .where(executions.c.workspace_id == workspace_id, executions.c.status == "succeeded")
            )
        ).scalar_one()
        lease_rows = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(worker_leases)
                .where(worker_leases.c.workspace_id == workspace_id)
            )
        ).scalar_one()
        epochs = (
            (await session.execute(sa.select(jobs.c.claim_epoch).where(jobs.c.workspace_id == workspace_id)))
            .scalars()
            .all()
        )
        owners = (
            (
                await session.execute(
                    sa.select(worker_leases.c.worker_id).where(worker_leases.c.workspace_id == workspace_id).distinct()
                )
            )
            .scalars()
            .all()
        )
    reserved_final = await _reserved_now(engines, workspace_id, user_id)

    events = await events_service.query_durable(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, limit=500
    )
    namespaces = {str(event["summary"].get("namespace", "")) for event in events}
    mixed = [event for event in events if event["summary"].get("namespace") != event["summary"].get("logical_key")]

    checks = [
        {
            "name": "all_executions_succeeded",
            "ok": int(succeeded) == TOTAL_EXECUTIONS,
            "detail": f"succeeded={succeeded}/{TOTAL_EXECUTIONS}",
        },
        {
            "name": "single_lease_per_job",
            "ok": int(lease_rows) == TOTAL_EXECUTIONS,
            "detail": f"worker_leases={lease_rows}",
        },
        {
            "name": "no_double_claim",
            "ok": all(int(epoch) == 1 for epoch in epochs),
            "detail": f"max_claim_epoch={max((int(e) for e in epochs), default=0)}",
        },
        {
            "name": "admission_peak_within_limit",
            "ok": peak_reserved <= int(ctx.thresholds["max_peak_reserved"]),
            "detail": f"peak_reserved={peak_reserved} limit={ctx.thresholds['max_peak_reserved']}",
        },
        {
            "name": "slots_released",
            "ok": reserved_final == 0,
            "detail": f"reserved_final={reserved_final}",
        },
        {
            "name": "parallel_wall_time",
            "ok": wall_seconds < (TOTAL_EXECUTIONS * FAKE_MODEL_LATENCY_SECONDS) / 2,
            "detail": f"wall={wall_seconds:.2f}s sequential≈{TOTAL_EXECUTIONS * FAKE_MODEL_LATENCY_SECONDS:.1f}s",
        },
        {
            "name": "events_per_execution",
            "ok": len(events) == TOTAL_EXECUTIONS,
            "detail": f"events={len(events)}",
        },
        {
            "name": "no_data_mixing",
            "ok": len(namespaces) == TOTAL_EXECUTIONS and not mixed,
            "detail": f"namespaces={len(namespaces)} mismatched={len(mixed)}",
        },
        {
            "name": "worker_utilization",
            "ok": len(set(owners)) >= 4,
            "detail": f"distinct_workers={len(set(owners))} done={results}",
        },
    ]
    ok = all(check["ok"] for check in checks) and wall_seconds <= float(ctx.thresholds["max_wall_seconds"])
    metrics = {
        "wall_seconds": wall_seconds,
        "peak_reserved": peak_reserved,
        "succeeded": int(succeeded),
        "worker_leases": int(lease_rows),
        "events_count": len(events),
        "fake_model_latency_seconds": FAKE_MODEL_LATENCY_SECONDS,
        "worker_count": WORKER_COUNT,
        "distinct_owners": sorted(str(owner) for owner in owners),
    }
    return {"ok": ok, "checks": checks, "metrics": metrics}
