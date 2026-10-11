from __future__ import annotations

import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from infra.workloads.common import WorkloadContext, percentile

RECORDS = 10000
PAGE_SIZE = 50
BASE_TIME = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
MAX_PAGING_PEAK_BYTES = 50 * 1024 * 1024


def _status_for(index: int) -> str:
    return "failed" if index % 10 == 0 else "succeeded"


def _verdict_for(index: int) -> str:
    if index % 3 == 0:
        return "passed"
    if index % 3 == 1:
        return "failed"
    return "inconclusive"


def _policy_for(index: int) -> str:
    return "llm" if index % 2 == 0 else "jev_cascade"


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.postgres import seed_workspace

    from agentqa.platform.runs.read_models import RunReadModel
    from agentqa.platform.storage.database import create_session_factory
    from agentqa.platform.storage.roles import ROLE_API
    from agentqa.platform.storage.scope import set_scope
    from agentqa.platform.storage.tables import run_snapshots, runs

    engines = ctx.engines
    user_id, workspace_id = await seed_workspace(engines, label="w4-history")
    env_a = uuid4()
    env_b = uuid4()
    run_rows = []
    snapshot_rows = []
    run_ids: list = []
    for index in range(RECORDS):
        run_id = uuid4()
        created_at = BASE_TIME - timedelta(minutes=index)
        run_ids.append(run_id)
        run_rows.append(
            {
                "id": run_id,
                "workspace_id": workspace_id,
                "status": _status_for(index),
                "verdict": _verdict_for(index),
                "gate": "passed" if _verdict_for(index) == "passed" else "rejected",
                "reasons": [],
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        snapshot_rows.append(
            {
                "id": uuid4(),
                "workspace_id": workspace_id,
                "run_id": run_id,
                "snapshot_version": 1,
                "content": {
                    "policy": _policy_for(index),
                    "observation_mode": "semantic",
                    "gate_profile": "strict",
                    "environment_revision": str(env_a if index % 2 == 0 else env_b),
                },
                "content_digest": f"{index:064d}",
                "created_at": created_at,
            }
        )

    insert_started = time.monotonic()
    factory = create_session_factory(engines[ROLE_API])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
        for offset in range(0, RECORDS, 1000):
            await session.execute(sa.insert(runs), run_rows[offset : offset + 1000])
            await session.execute(sa.insert(run_snapshots), snapshot_rows[offset : offset + 1000])
    insert_seconds = time.monotonic() - insert_started

    read_model = RunReadModel(engines[ROLE_API])
    expected = {
        "total": RECORDS,
        "verdict_passed": sum(1 for index in range(RECORDS) if _verdict_for(index) == "passed"),
        "verdict_failed": sum(1 for index in range(RECORDS) if _verdict_for(index) == "failed"),
        "policy_jev_cascade": sum(1 for index in range(RECORDS) if _policy_for(index) == "jev_cascade"),
        "environment_a": sum(1 for index in range(RECORDS) if index % 2 == 0),
        "status_succeeded": sum(1 for index in range(RECORDS) if _status_for(index) == "succeeded"),
        "date_first_day": sum(
            1 for index in range(RECORDS) if BASE_TIME - timedelta(minutes=index) >= BASE_TIME - timedelta(days=1)
        ),
    }

    query_times: list[float] = []
    paging_started = time.monotonic()
    tracemalloc.start()
    page = await read_model.run_list(workspace_id=workspace_id, principal_id=user_id, limit=PAGE_SIZE)
    query_times.append(time.monotonic() - paging_started)
    seen_ids: set = set()
    for item in page["items"]:
        seen_ids.add(item["run_id"])
    pages = 1
    cursor = page["next_cursor"]
    while cursor is not None:
        started = time.monotonic()
        after_created, after_id = cursor.split("|")
        page = await read_model.run_list(
            workspace_id=workspace_id,
            principal_id=user_id,
            limit=PAGE_SIZE,
            after=(after_created, after_id),
        )
        query_times.append(time.monotonic() - started)
        pages += 1
        for item in page["items"]:
            seen_ids.add(item["run_id"])
        cursor = page["next_cursor"]
    _, paging_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    paging_seconds = time.monotonic() - paging_started

    filter_started = time.monotonic()
    passed_page = await read_model.run_list(workspace_id=workspace_id, principal_id=user_id, verdict="passed", limit=1)
    query_times.append(time.monotonic() - filter_started)
    started = time.monotonic()
    cascade_page = await read_model.run_list(
        workspace_id=workspace_id, principal_id=user_id, policy="jev_cascade", limit=1
    )
    query_times.append(time.monotonic() - started)
    started = time.monotonic()
    env_page = await read_model.run_list(
        workspace_id=workspace_id, principal_id=user_id, environment_revision_id=env_a, limit=1
    )
    query_times.append(time.monotonic() - started)
    started = time.monotonic()
    date_page = await read_model.run_list(
        workspace_id=workspace_id,
        principal_id=user_id,
        date_from=(BASE_TIME - timedelta(days=1)).isoformat(),
        date_to=BASE_TIME.isoformat(),
        limit=1,
    )
    query_times.append(time.monotonic() - started)

    comparison = await read_model.run_comparison(
        workspace_id=workspace_id, principal_id=user_id, run_a=run_ids[0], run_b=run_ids[1]
    )
    env_diff = None
    if comparison is not None:
        for row in comparison.get("config_diff", []):
            if row["field"] == "environment_revision":
                env_diff = row

    read_p95 = percentile(query_times, 0.95)
    checks = [
        {
            "name": "paging_complete",
            "ok": pages == RECORDS // PAGE_SIZE and len(seen_ids) == RECORDS,
            "detail": f"pages={pages} unique={len(seen_ids)}",
        },
        {
            "name": "scoped_counts",
            "ok": int(date_page["total"]) == expected["date_first_day"]
            and int(passed_page["total"]) == expected["verdict_passed"]
            and int(cascade_page["total"]) == expected["policy_jev_cascade"]
            and int(env_page["total"]) == expected["environment_a"],
            "detail": (
                f"date={date_page['total']}/{expected['date_first_day']} "
                f"passed={passed_page['total']}/{expected['verdict_passed']} "
                f"cascade={cascade_page['total']}/{expected['policy_jev_cascade']} "
                f"env_a={env_page['total']}/{expected['environment_a']}"
            ),
        },
        {
            "name": "p95_read_budget",
            "ok": read_p95 <= float(ctx.thresholds["p95_read_seconds"]),
            "detail": f"p95={read_p95:.4f}s limit={ctx.thresholds['p95_read_seconds']}s queries={len(query_times)}",
        },
        {
            "name": "bounded_paging_memory",
            "ok": paging_peak <= MAX_PAGING_PEAK_BYTES,
            "detail": f"peak={paging_peak} bytes limit={MAX_PAGING_PEAK_BYTES}",
        },
        {
            "name": "compare_config_diff",
            "ok": env_diff is not None and env_diff["equal"] is False,
            "detail": f"environment_diff={env_diff}",
        },
    ]
    total_seconds = insert_seconds + paging_seconds
    ok = all(check["ok"] for check in checks) and total_seconds <= float(ctx.thresholds["max_wall_seconds"])
    metrics = {
        "insert_seconds": insert_seconds,
        "read_p95_seconds": read_p95,
        "read_queries": len(query_times),
        "paging_peak_bytes": paging_peak,
        "pages": pages,
        "records": RECORDS,
        "expected_counts": expected,
    }
    return {"ok": ok, "checks": checks, "metrics": metrics}
