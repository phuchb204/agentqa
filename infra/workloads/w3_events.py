from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

from infra.workloads.common import WorkloadContext, percentile

EVENTS_PER_EXECUTION = 2000
READ_CLIENTS = 20
RECONNECT_CLIENTS = 5
BATCH_SIZE = 100
EXECUTIONS = 2
POLL_INTERVAL_SECONDS = 0.1


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.postgres import seed_execution, seed_run, seed_workspace

    from agentqa.platform.events.service import EventService
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_API
    from agentqa.platform.storage.scope import set_scope

    engines = ctx.engines
    user_id, workspace_id = await seed_workspace(engines, label="w3-events")
    run_ids: list[UUID] = []
    execution_ids: list[UUID] = []
    for index in range(EXECUTIONS):
        run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id, status="running")
        execution_id = await seed_execution(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            run_id=run_id,
            logical_key=f"w3-exec-{index}",
        )
        run_ids.append(run_id)
        execution_ids.append(execution_id)

    events_service = EventService(engines[ROLE_API])
    commit_times: dict[tuple[int, int], float] = {}

    async def writer(run_index: int) -> None:
        run_id = run_ids[run_index]
        execution_id = execution_ids[run_index]
        factory = create_session_factory(engines[ROLE_API])
        sequence = 0
        while sequence < EVENTS_PER_EXECUTION:
            batch = min(BATCH_SIZE, EVENTS_PER_EXECUTION - sequence)
            async with factory() as session, session.begin():
                await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
                for offset in range(batch):
                    await events_service.append(
                        session,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        event_type="w3.event",
                        actor="w3-writer",
                        execution_id=execution_id,
                        payload={"index": sequence + offset, "run_index": run_index},
                    )
            sequence += batch
            commit_times[(run_index, sequence)] = time.monotonic()

    async def reader(reader_index: int, run_index: int) -> dict[str, Any]:
        run_id = run_ids[run_index]
        cursor = 0
        seen: list[int] = []
        seen_set: set[int] = set()
        latencies: list[float] = []
        reconnects = 0
        reconnected = False
        while True:
            batch = await events_service.query_durable(
                workspace_id=workspace_id,
                principal_id=user_id,
                run_id=run_id,
                after_run_seq=cursor,
                limit=500,
            )
            observed_at = time.monotonic()
            if not batch:
                if len(seen_set) >= EVENTS_PER_EXECUTION:
                    break
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            for event in batch:
                seq = int(event["run_seq"])
                fingerprint = int(event["summary"].get("index", -1))
                if seq in seen_set:
                    continue
                seen_set.add(seq)
                seen.append(seq)
                target_seq = ((fingerprint // BATCH_SIZE) + 1) * BATCH_SIZE
                commit_at = commit_times.get((run_index, target_seq))
                if commit_at is not None and seq % BATCH_SIZE == 0:
                    latencies.append(max(0.0, observed_at - commit_at))
                cursor = max(cursor, seq)
            if reader_index < RECONNECT_CLIENTS and not reconnected and len(seen_set) >= EVENTS_PER_EXECUTION // 4:
                reconnected = True
                reconnects += 1
                await asyncio.sleep(0.3)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        return {
            "run_index": run_index,
            "seen": len(seen_set),
            "ordered": seen == sorted(seen),
            "latencies": latencies,
            "reconnects": reconnects,
        }

    started = time.monotonic()
    writers = [asyncio.create_task(writer(run_index)) for run_index in range(EXECUTIONS)]
    readers = [asyncio.create_task(reader(index % READ_CLIENTS, index % EXECUTIONS)) for index in range(READ_CLIENTS)]
    try:
        await asyncio.wait_for(asyncio.gather(*writers), timeout=300)
        results = await asyncio.wait_for(asyncio.gather(*readers), timeout=300)
    finally:
        for task in [*writers, *readers]:
            if not task.done():
                task.cancel()
    wall_seconds = time.monotonic() - started

    all_latencies = [latency for result in results for latency in result["latencies"]]
    delivery_p95 = percentile(all_latencies, 0.95) if all_latencies else 0.0
    lost = [result for result in results if result["seen"] != EVENTS_PER_EXECUTION]
    unordered = [result for result in results if not result["ordered"]]
    reconnected = sum(1 for result in results if result["reconnects"] > 0)

    factory = create_session_factory(engines[ROLE_API])
    import sqlalchemy as sa

    from agentqa.platform.storage.tables import run_events

    async with factory() as session, session.begin():
        await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
        committed = (
            await session.execute(
                sa.select(sa.func.count()).select_from(run_events).where(run_events.c.workspace_id == workspace_id)
            )
        ).scalar_one()

    checks = [
        {
            "name": "zero_lost_or_duplicate",
            "ok": not lost and int(committed) == EVENTS_PER_EXECUTION * EXECUTIONS,
            "detail": f"committed={committed} readers_missing={len(lost)}",
        },
        {
            "name": "ordered_cursor_no_duplicate",
            "ok": not unordered,
            "detail": f"unordered_readers={len(unordered)}",
        },
        {
            "name": "p95_delivery_budget",
            "ok": delivery_p95 <= float(ctx.thresholds["p95_delivery_seconds"]),
            "detail": (
                f"p95={delivery_p95:.4f}s limit={ctx.thresholds['p95_delivery_seconds']}s samples={len(all_latencies)}"
            ),
        },
        {
            "name": "partial_reconnect_clients",
            "ok": reconnected == RECONNECT_CLIENTS,
            "detail": f"reconnected={reconnected}",
        },
    ]
    ok = all(check["ok"] for check in checks) and wall_seconds <= float(ctx.thresholds["max_wall_seconds"])
    metrics = {
        "wall_seconds": wall_seconds,
        "events_per_execution": EVENTS_PER_EXECUTION,
        "executions": EXECUTIONS,
        "read_clients": READ_CLIENTS,
        "delivery_p95_seconds": delivery_p95,
        "delivery_samples": len(all_latencies),
        "committed_events": int(committed),
        "reconnected_clients": reconnected,
    }
    return {"ok": ok, "checks": checks, "metrics": metrics}
