from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.support.platform import (
    service_case_revision,
    service_dataset_revision,
    service_suite_revision,
    service_workspace,
    suite_content,
)
from tests.support.postgres import scoped_transaction

from agentqa.contracts.errors import AgentQAValidationError
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.runs.service import RunService
from agentqa.platform.scheduler import SchedulerService
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


def _schedule_content(suite_revision_id, *, hour: int, minute: int = 0, tz: str = "UTC", overlap: str = "skip") -> dict:
    return {
        "schema_version": "schedule/1",
        "logical_key": "nightly",
        "suite_revision_id": str(suite_revision_id),
        "timezone": tz,
        "hour": hour,
        "minute": minute,
        "days_of_week": [],
        "overlap": overlap,
    }


async def _setup(runtime, *, hour: int = 8, overlap: str = "skip", now: datetime | None = None):
    user_id, username, workspace_id = await service_workspace(runtime)
    case = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="sched_case"
    )
    dataset = await service_dataset_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="sched_rows",
        rows=[{"item": "x"}],
    )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="sched_suite",
        content=suite_content(
            "sched_suite",
            case_refs=[{"logical_key": "sched_case", "revision_no": case.revision_no}],
            dataset_ref="sched_rows",
            dataset_revision_no=dataset.revision_no,
        ),
    )
    engine = runtime.engines[ROLE_WORKER]
    runs = RunService(engine)
    clock = (lambda: now) if now is not None else None
    scheduler = SchedulerService(engine, run_service=runs, clock=clock)
    schedule_id = await scheduler.create_schedule(
        workspace_id=workspace_id, principal_id=user_id, logical_key="nightly"
    )
    await scheduler.add_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        schedule_id=schedule_id,
        content=_schedule_content(suite.revision_id, hour=hour, overlap=overlap),
    )
    return user_id, workspace_id, scheduler, schedule_id, suite


async def _count(runtime, workspace_id, user_id, table) -> int:
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


async def test_materialize_and_claim_creates_pinned_suite_run(runtime) -> None:
    early = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, schedule_id, suite = await _setup(runtime, hour=8, now=early)
    created = await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id)
    states = {occurrence.local_wall_time.date().isoformat(): occurrence.state for occurrence in created}
    assert states["2026-06-15"] == "pending"
    assert states["2026-06-14"] == "missed"
    assert states["2026-06-13"] == "missed"

    claimed_early = await scheduler.claim_due(workspace_id=workspace_id, principal_id=user_id, worker_id="sched-1")
    assert claimed_early == []
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 0

    due = datetime(2026, 6, 15, 8, 5, tzinfo=UTC)
    claimed = await scheduler.claim_due(workspace_id=workspace_id, principal_id=user_id, worker_id="sched-1", now=due)
    assert len(claimed) == 1
    occurrence = claimed[0]
    assert occurrence.state == "claimed"
    assert occurrence.run_id is not None
    assert occurrence.local_wall_time.date().isoformat() == "2026-06-15"

    snapshots = await _fetch(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.run_snapshots.c.content).where(tables.run_snapshots.c.run_id == occurrence.run_id),
    )
    assert snapshots[0].content["suite_revision"] == str(suite.revision_id)
    executions = await _count(runtime, workspace_id, user_id, tables.executions)
    jobs = await _count(runtime, workspace_id, user_id, tables.jobs)
    assert executions == 1
    assert jobs == 1
    again = await scheduler.claim_due(workspace_id=workspace_id, principal_id=user_id, worker_id="sched-2", now=due)
    assert again == []
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1
    occurrences = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    claimed_rows = [row for row in occurrences if row.state == "claimed"]
    assert len(claimed_rows) == 1


async def _fetch(runtime, workspace_id, user_id, statement):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(statement)).all()


async def test_overlap_skip_then_queue_after_terminal(runtime) -> None:
    day1 = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, schedule_id, _suite = await _setup(runtime, hour=8, overlap="skip", now=day1)
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id)
    first = await scheduler.claim_due(
        workspace_id=workspace_id,
        principal_id=user_id,
        worker_id="sched-1",
        now=datetime(2026, 6, 15, 8, 5, tzinfo=UTC),
    )
    assert len(first) == 1
    second_day = datetime(2026, 6, 16, 8, 5, tzinfo=UTC)
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=second_day)
    second = await scheduler.claim_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="sched-2", now=second_day
    )
    assert second == []
    occurrences = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    day2 = [row for row in occurrences if row.local_wall_time.date().isoformat() == "2026-06-16"]
    assert [row.state for row in day2] == ["skipped"]
    assert day2[0].reason == "overlap_skip"

    queue_user, queue_workspace, queue_scheduler, queue_schedule, _ = await _setup(
        runtime, hour=8, overlap="queue", now=day1
    )
    await queue_scheduler.materialize_due(workspace_id=queue_workspace, principal_id=queue_user)
    await queue_scheduler.claim_due(
        workspace_id=queue_workspace,
        principal_id=queue_user,
        worker_id="sched-1",
        now=datetime(2026, 6, 15, 8, 5, tzinfo=UTC),
    )
    await queue_scheduler.materialize_due(workspace_id=queue_workspace, principal_id=queue_user, now=second_day)
    queued_claim = await queue_scheduler.claim_due(
        workspace_id=queue_workspace, principal_id=queue_user, worker_id="sched-2", now=second_day
    )
    assert queued_claim == []
    queued = await queue_scheduler.list_occurrences(
        workspace_id=queue_workspace, principal_id=queue_user, schedule_id=queue_schedule
    )
    queued_day2 = [row for row in queued if row.local_wall_time.date().isoformat() == "2026-06-16"]
    assert [row.state for row in queued_day2] == ["queued"]
    first_run_id = next(row.run_id for row in queued if row.state == "claimed")
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=queue_user, workspace_id=queue_workspace
    ) as session:
        await session.execute(sa.update(tables.runs).where(tables.runs.c.id == first_run_id).values(status="succeeded"))
    promoted = await queue_scheduler.claim_due(
        workspace_id=queue_workspace, principal_id=queue_user, worker_id="sched-3", now=second_day
    )
    assert len(promoted) == 1
    assert promoted[0].state == "claimed"
    assert promoted[0].run_id is not None


async def test_downtime_does_not_catch_up_runs(runtime) -> None:
    day1 = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, _schedule_id, _suite = await _setup(runtime, hour=8, now=day1)
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id)
    restarted = datetime(2026, 6, 18, 9, 30, tzinfo=UTC)
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=restarted)
    after_downtime = await scheduler.list_occurrences(workspace_id=workspace_id, principal_id=user_id)
    states = {occurrence.local_wall_time.date().isoformat(): occurrence.state for occurrence in after_downtime}
    assert states.get("2026-06-16") == "missed"
    assert states.get("2026-06-17") == "missed"
    assert states.get("2026-06-18") == "missed"
    claimed = await scheduler.claim_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="sched-1", now=restarted
    )
    assert claimed == []
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 0
    next_slot = datetime(2026, 6, 19, 8, 5, tzinfo=UTC)
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=next_slot)
    resumed = await scheduler.claim_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="sched-1", now=next_slot
    )
    assert len(resumed) == 1
    assert resumed[0].run_id is not None
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1


async def test_multi_scheduler_single_winner(runtime) -> None:
    day = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    user_id, workspace_id, _scheduler, _schedule_id, _suite = await _setup(runtime, hour=8, now=day)
    engine = runtime.engines[ROLE_WORKER]
    schedulers = [SchedulerService(engine, run_service=RunService(engine)) for _ in range(4)]
    await schedulers[0].materialize_due(workspace_id=workspace_id, principal_id=user_id, now=day)
    due = datetime(2026, 6, 15, 8, 5, tzinfo=UTC)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                scheduler.claim_due(
                    workspace_id=workspace_id, principal_id=user_id, worker_id=f"sched-{index}", now=due
                )
                for index, scheduler in enumerate(schedulers)
            )
        ),
        timeout=30,
    )
    winners = [occurrence for batch in results for occurrence in batch]
    assert len(winners) == 1
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1


async def test_materialize_is_idempotent(runtime) -> None:
    day = datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, _schedule_id, _suite = await _setup(runtime, hour=8, now=day)
    first = await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id)
    second = await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id)
    assert {row.occurrence_key for row in first}.isdisjoint({row.occurrence_key for row in second} or set())
    assert len({row.occurrence_key for row in first}) == len(first)
    total = await _count(runtime, workspace_id, user_id, tables.schedule_occurrences)
    assert total == len(first)
    assert len(second) <= 4


async def _create_entity(api_client, csrf: str, workspace_id: str, kind: str, logical_key: str) -> str:
    from tests.support.security import csrf_headers

    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/{kind}s",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_schedule_api_crud(api_client, owner) -> None:
    from tests.support.security import csrf_headers

    workspace_id, csrf = owner
    case_id = await _create_entity(api_client, csrf, workspace_id, "case", "api_case")
    case_content = {
        "schema_version": "case/1",
        "logical_key": "api_case",
        "title": "Ca API",
        "goal": "Kiểm tra",
        "requirements": ["r"],
        "nodes": [
            {
                "id": "open",
                "kind": "action",
                "operation": "navigate",
                "value": {"kind": "literal", "value": "/start"},
                "side_effect": "read",
            },
            {
                "id": "check",
                "kind": "checkpoint",
                "assertions": [
                    {
                        "id": "reached",
                        "required": True,
                        "comparator": "url_path_equals",
                        "expected": {"kind": "literal", "value": "/start"},
                        "source_refs": ["r"],
                    }
                ],
            },
        ],
        "source_defs": {
            "r": {
                "source_content_digest": "a" * 64,
                "anchor": {"type": "section", "value": "flow"},
                "quote_digest": "b" * 64,
                "provenance": "user",
            }
        },
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["reached"]},
    }
    patched = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": case_content},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert patched.status_code == 200, patched.text
    promoted_case = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert promoted_case.status_code == 200, promoted_case.text
    suite_id = await _create_entity(api_client, csrf, workspace_id, "suite", "api_suite")
    promoted_suite = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={
            "content": {
                "schema_version": "suite/1",
                "logical_key": "api_suite",
                "case_refs": [{"logical_key": "api_case", "revision_no": 1}],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert promoted_suite.status_code == 200, promoted_suite.text
    suite_revision_id = promoted_suite.json()["revision_id"]

    created = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/schedules",
        json={"logical_key": "api_schedule"},
        headers=csrf_headers(csrf),
    )
    assert created.status_code == 200, created.text
    schedule_id = created.json()["schedule_id"]
    revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/revisions",
        json={
            "content": {
                "schema_version": "schedule/1",
                "logical_key": "api_schedule",
                "suite_revision_id": suite_revision_id,
                "timezone": "UTC",
                "hour": 8,
                "minute": 0,
                "overlap": "skip",
            }
        },
        headers=csrf_headers(csrf),
    )
    assert revision.status_code == 200, revision.text
    assert revision.json()["revision_no"] == 1
    listed = await api_client.get(f"/api/v1/workspaces/{workspace_id}/schedules")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["enabled"] is True
    assert items[0]["latest_revision"]["revision_no"] == 1
    occurrences = await api_client.get(f"/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/occurrences")
    assert occurrences.status_code == 200
    assert occurrences.json()["items"] == []
    disabled = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/disable",
        headers=csrf_headers(csrf),
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    relisted = await api_client.get(f"/api/v1/workspaces/{workspace_id}/schedules")
    assert relisted.json()["items"][0]["enabled"] is False


async def test_invalid_schedule_content_rejected(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    scheduler = SchedulerService(runtime.engines[ROLE_WORKER], run_service=RunService(runtime.engines[ROLE_WORKER]))
    schedule_id = await scheduler.create_schedule(
        workspace_id=workspace_id, principal_id=user_id, logical_key=f"bad-{uuid4().hex[:6]}"
    )
    with pytest.raises((AgentQAValidationError, IdentityError)):
        await scheduler.add_revision(
            workspace_id=workspace_id,
            principal_id=user_id,
            schedule_id=schedule_id,
            content=_schedule_content(uuid4(), hour=8, tz="Not/AZone"),
        )
