from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from tests.support.platform import (
    service_case_revision,
    service_suite_revision,
    service_workspace,
    suite_content,
)
from tests.support.postgres import scoped_transaction

from agentqa.platform.runs.service import RunService
from agentqa.platform.scheduler import SchedulerService
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


async def _scheduler_with_slot(runtime, *, tz: str, hour: int, minute: int, now: datetime):
    user_id, username, workspace_id = await service_workspace(runtime)
    case = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="dst_case"
    )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="dst_suite",
        content=suite_content(
            "dst_suite",
            case_refs=[{"logical_key": "dst_case", "revision_no": case.revision_no}],
        ),
    )
    engine = runtime.engines[ROLE_WORKER]
    scheduler = SchedulerService(engine, run_service=RunService(engine), clock=lambda: now)
    schedule_id = await scheduler.create_schedule(
        workspace_id=workspace_id, principal_id=user_id, logical_key="dst_schedule"
    )
    await scheduler.add_revision(
        workspace_id=workspace_id,
        principal_id=user_id,
        schedule_id=schedule_id,
        content={
            "schema_version": "schedule/1",
            "logical_key": "dst_schedule",
            "suite_revision_id": str(suite.revision_id),
            "timezone": tz,
            "hour": hour,
            "minute": minute,
            "days_of_week": [],
            "overlap": "skip",
        },
    )
    return user_id, workspace_id, scheduler, schedule_id


async def _runs_count(runtime, workspace_id, user_id) -> int:
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(sa.select(sa.func.count()).select_from(tables.runs))).scalar_one()


async def test_dst_gap_creates_skipped_receipt_without_run(runtime) -> None:
    tz = ZoneInfo("America/New_York")
    naive = datetime(2026, 3, 8, 2, 30)
    assert naive.replace(tzinfo=tz).astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, schedule_id = await _scheduler_with_slot(
        runtime, tz="America/New_York", hour=2, minute=30, now=now
    )
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=now)
    occurrences = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    gap_day = [row for row in occurrences if row.local_wall_time.date().isoformat() == "2026-03-08"]
    assert len(gap_day) == 1
    assert gap_day[0].state == "skipped"
    assert gap_day[0].reason == "dst_gap"
    assert gap_day[0].fold == 0
    assert gap_day[0].scheduled_at is not None
    assert gap_day[0].scheduled_at.astimezone(tz).hour == 3

    later = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
    claimed = await scheduler.claim_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="dst-worker", now=later
    )
    assert all(row.state != "claimed" for row in claimed) or claimed == []
    assert await _runs_count(runtime, workspace_id, user_id) == 0


async def test_dst_fold_creates_single_occurrence(runtime) -> None:
    tz = ZoneInfo("Europe/Berlin")
    naive = datetime(2026, 10, 25, 2, 30)
    fold_zero = naive.replace(tzinfo=tz, fold=0).utcoffset()
    fold_one = naive.replace(tzinfo=tz, fold=1).utcoffset()
    assert fold_zero != fold_one
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, schedule_id = await _scheduler_with_slot(
        runtime, tz="Europe/Berlin", hour=2, minute=30, now=now
    )
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=now)
    occurrences = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    fold_day = [row for row in occurrences if row.local_wall_time.date().isoformat() == "2026-10-25"]
    assert len(fold_day) == 1
    assert fold_day[0].fold == 0
    assert fold_day[0].state == "pending"

    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=now)
    occurrences_again = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    fold_day_again = [row for row in occurrences_again if row.local_wall_time.date().isoformat() == "2026-10-25"]
    assert len(fold_day_again) == 1

    due = datetime(2026, 10, 25, 2, 5, tzinfo=UTC)
    claimed = await scheduler.claim_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="dst-worker", now=due
    )
    assert len(claimed) == 1
    assert await _runs_count(runtime, workspace_id, user_id) == 1


async def test_dst_gap_day_other_slot_still_pending(runtime) -> None:
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    user_id, workspace_id, scheduler, schedule_id = await _scheduler_with_slot(
        runtime, tz="America/New_York", hour=10, minute=0, now=now
    )
    await scheduler.materialize_due(workspace_id=workspace_id, principal_id=user_id, now=now)
    occurrences = await scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=user_id, schedule_id=schedule_id
    )
    gap_day = [row for row in occurrences if row.local_wall_time.date().isoformat() == "2026-03-08"]
    assert len(gap_day) == 1
    assert gap_day[0].state == "pending"
    assert gap_day[0].reason is None
