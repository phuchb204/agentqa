from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import StrictModel
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.runs.service import RunService, SubmitRequest
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

DEFAULT_GRACE_MINUTES = 60
DEFAULT_LOOKBACK_DAYS = 2
TERMINAL_RUN_STATUSES = ("succeeded", "failed", "cancelled", "error", "inconclusive")


class ScheduleContent(StrictModel):
    schema_version: str
    logical_key: str
    suite_revision_id: UUID
    timezone: str
    hour: int
    minute: int = 0
    days_of_week: list[int] = Field(default_factory=list)
    overlap: str = "skip"
    environment_revision_id: UUID | None = None
    catch_up_grace_minutes: int = DEFAULT_GRACE_MINUTES


@dataclass(frozen=True)
class ScheduleOccurrence:
    occurrence_id: UUID
    schedule_id: UUID
    schedule_revision_id: UUID
    occurrence_key: str
    local_wall_time: datetime
    scheduled_at: datetime | None
    fold: int
    state: str
    reason: str | None
    run_id: UUID | None


def validate_schedule_content(content: dict) -> ScheduleContent:
    try:
        parsed = ScheduleContent.model_validate(content)
    except Exception as error:
        raise IdentityError(ErrorCode.INPUT_INVALID, f"schedule content không hợp lệ: {error}") from error
    errors: list = []
    if parsed.schema_version != "schedule/1":
        errors.append(field_error(("schema_version",), ErrorCode.INPUT_INVALID, "chỉ hỗ trợ schedule/1"))
    if not (0 <= parsed.hour <= 23):
        errors.append(field_error(("hour",), ErrorCode.INPUT_INVALID, "hour phải trong 0..23"))
    if not (0 <= parsed.minute <= 59):
        errors.append(field_error(("minute",), ErrorCode.INPUT_INVALID, "minute phải trong 0..59"))
    if any(day < 0 or day > 6 for day in parsed.days_of_week):
        errors.append(field_error(("days_of_week",), ErrorCode.INPUT_INVALID, "days_of_week dùng 0..6"))
    if parsed.overlap not in ("skip", "queue"):
        errors.append(field_error(("overlap",), ErrorCode.INPUT_INVALID, "overlap phải là skip hoặc queue"))
    try:
        ZoneInfo(parsed.timezone)
    except Exception:
        errors.append(field_error(("timezone",), ErrorCode.INPUT_INVALID, "timezone IANA không hợp lệ"))
    if errors:
        raise AgentQAValidationError(errors)
    return parsed


def _slot_utc(local_day: date, hour: int, minute: int, tz: ZoneInfo) -> tuple[datetime | None, bool]:
    naive = datetime.combine(local_day, time(hour=hour, minute=minute))
    local = naive.replace(tzinfo=tz, fold=0)
    as_utc = local.astimezone(UTC)
    round_trip = as_utc.astimezone(tz)
    if round_trip.replace(tzinfo=None) != naive:
        return as_utc, True
    return as_utc, False


class SchedulerService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        run_service: RunService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._runs = run_service or RunService(engine)
        self._clock = clock or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        moment = self._clock()
        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)
        return moment

    async def create_schedule(self, *, workspace_id: UUID, principal_id: UUID, logical_key: str) -> UUID:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            schedule_id = (
                await session.execute(
                    pg_insert(tables.schedules)
                    .values(id=uuid4(), workspace_id=workspace_id, logical_key=logical_key, enabled=True)
                    .on_conflict_do_nothing(index_elements=["workspace_id", "logical_key"])
                    .returning(tables.schedules.c.id)
                )
            ).scalar_one_or_none()
            if schedule_id is None:
                schedule_id = (
                    await session.execute(
                        sa.select(tables.schedules.c.id).where(
                            tables.schedules.c.workspace_id == workspace_id,
                            tables.schedules.c.logical_key == logical_key,
                        )
                    )
                ).scalar_one()
        return schedule_id

    async def add_revision(
        self, *, workspace_id: UUID, principal_id: UUID, schedule_id: UUID, content: dict
    ) -> tuple[UUID, int]:
        parsed = validate_schedule_content(content)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            schedule = (
                await session.execute(
                    sa.select(tables.schedules.c.id).where(
                        tables.schedules.c.workspace_id == workspace_id, tables.schedules.c.id == schedule_id
                    )
                )
            ).one_or_none()
            if schedule is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy schedule trong scope")
            suite_revision = (
                await session.execute(
                    sa.select(tables.suite_revisions.c.id).where(
                        tables.suite_revisions.c.workspace_id == workspace_id,
                        tables.suite_revisions.c.id == parsed.suite_revision_id,
                    )
                )
            ).one_or_none()
            if suite_revision is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "suite revision của schedule không tồn tại trong scope")
            latest = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.max(tables.schedule_revisions.c.revision_no), 0)).where(
                        tables.schedule_revisions.c.schedule_id == schedule_id
                    )
                )
            ).scalar_one()
            revision_no = int(latest) + 1
            revision_id = uuid4()
            await session.execute(
                sa.insert(tables.schedule_revisions).values(
                    id=revision_id,
                    workspace_id=workspace_id,
                    schedule_id=schedule_id,
                    revision_no=revision_no,
                    content=content,
                    content_digest=digest_content(content),
                )
            )
        return revision_id, revision_no

    async def set_enabled(self, *, workspace_id: UUID, principal_id: UUID, schedule_id: UUID, enabled: bool) -> None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            updated = (
                await session.execute(
                    sa.update(tables.schedules)
                    .where(tables.schedules.c.workspace_id == workspace_id, tables.schedules.c.id == schedule_id)
                    .values(enabled=enabled, updated_at=sa.func.now())
                    .returning(tables.schedules.c.id)
                )
            ).scalar_one_or_none()
            if updated is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy schedule trong scope")

    async def list_schedules(self, *, workspace_id: UUID, principal_id: UUID) -> list[dict[str, Any]]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(
                        tables.schedules.c.id,
                        tables.schedules.c.logical_key,
                        tables.schedules.c.enabled,
                    )
                    .where(tables.schedules.c.workspace_id == workspace_id)
                    .order_by(tables.schedules.c.created_at, tables.schedules.c.id)
                )
            ).all()
            revisions = (
                await session.execute(
                    sa.select(
                        tables.schedule_revisions.c.schedule_id,
                        tables.schedule_revisions.c.id,
                        tables.schedule_revisions.c.revision_no,
                        tables.schedule_revisions.c.content,
                    ).where(tables.schedule_revisions.c.workspace_id == workspace_id)
                )
            ).all()
        latest: dict[UUID, Any] = {}
        for revision in revisions:
            current = latest.get(revision.schedule_id)
            if current is None or revision.revision_no > current.revision_no:
                latest[revision.schedule_id] = revision
        return [
            {
                "schedule_id": row.id,
                "logical_key": row.logical_key,
                "enabled": bool(row.enabled),
                "latest_revision": (
                    {
                        "revision_id": latest[row.id].id,
                        "revision_no": latest[row.id].revision_no,
                        "content": latest[row.id].content,
                    }
                    if row.id in latest
                    else None
                ),
            }
            for row in rows
        ]

    async def list_occurrences(
        self, *, workspace_id: UUID, principal_id: UUID, schedule_id: UUID | None = None, limit: int = 100
    ) -> list[ScheduleOccurrence]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            statement = (
                sa.select(tables.schedule_occurrences)
                .where(tables.schedule_occurrences.c.workspace_id == workspace_id)
                .order_by(tables.schedule_occurrences.c.local_wall_time, tables.schedule_occurrences.c.id)
                .limit(limit)
            )
            if schedule_id is not None:
                statement = statement.where(tables.schedule_occurrences.c.schedule_id == schedule_id)
            rows = (await session.execute(statement)).all()
        return [
            ScheduleOccurrence(
                occurrence_id=row.id,
                schedule_id=row.schedule_id,
                schedule_revision_id=row.schedule_revision_id,
                occurrence_key=row.occurrence_key,
                local_wall_time=row.local_wall_time,
                scheduled_at=row.scheduled_at,
                fold=row.fold,
                state=row.state,
                reason=row.reason,
                run_id=row.run_id,
            )
            for row in rows
        ]

    def _latest_revision_for(self, revisions: list[Any], schedule_id: UUID) -> Any:
        selected = [revision for revision in revisions if revision.schedule_id == schedule_id]
        if not selected:
            return None
        return max(selected, key=lambda revision: revision.revision_no)

    async def materialize_due(
        self, *, workspace_id: UUID, principal_id: UUID, now: datetime | None = None
    ) -> list[ScheduleOccurrence]:
        moment = now or self.now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        created: list[ScheduleOccurrence] = []
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            schedules = (
                await session.execute(
                    sa.select(tables.schedules.c.id).where(
                        tables.schedules.c.workspace_id == workspace_id, tables.schedules.c.enabled.is_(True)
                    )
                )
            ).all()
            revisions = (
                await session.execute(
                    sa.select(
                        tables.schedule_revisions.c.schedule_id,
                        tables.schedule_revisions.c.id,
                        tables.schedule_revisions.c.revision_no,
                        tables.schedule_revisions.c.content,
                    ).where(tables.schedule_revisions.c.workspace_id == workspace_id)
                )
            ).all()
            for schedule in schedules:
                revision = self._latest_revision_for(revisions, schedule.id)
                if revision is None:
                    continue
                content = validate_schedule_content(revision.content)
                tz = ZoneInfo(content.timezone)
                local_now = moment.astimezone(tz)
                lookback_start = local_now.date() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
                for offset in range(DEFAULT_LOOKBACK_DAYS + 2):
                    local_day = lookback_start + timedelta(days=offset)
                    if content.days_of_week and local_day.weekday() not in content.days_of_week:
                        continue
                    as_utc, is_gap = _slot_utc(local_day, content.hour, content.minute, tz)
                    naive = datetime.combine(local_day, time(hour=content.hour, minute=content.minute))
                    occurrence_key = f"{revision.id}:{naive.isoformat(timespec='minutes')}:fold0"
                    grace = timedelta(minutes=content.catch_up_grace_minutes)
                    if is_gap:
                        state = "skipped"
                        reason = "dst_gap"
                    elif as_utc is not None and as_utc + grace < moment:
                        state = "missed"
                        reason = "downtime"
                    else:
                        state = "pending"
                        reason = None
                    existing = (
                        await session.execute(
                            sa.select(tables.schedule_occurrences.c.id).where(
                                tables.schedule_occurrences.c.schedule_revision_id == revision.id,
                                tables.schedule_occurrences.c.occurrence_key == occurrence_key,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        continue
                    occurrence_id = (
                        await session.execute(
                            pg_insert(tables.schedule_occurrences)
                            .values(
                                id=uuid4(),
                                workspace_id=workspace_id,
                                schedule_id=schedule.id,
                                schedule_revision_id=revision.id,
                                occurrence_key=occurrence_key,
                                local_wall_time=naive,
                                scheduled_at=as_utc,
                                fold=0,
                                state=state,
                                reason=reason,
                            )
                            .on_conflict_do_nothing(constraint="uq_schedule_occurrences_key")
                            .returning(tables.schedule_occurrences.c.id)
                        )
                    ).scalar_one_or_none()
                    if occurrence_id is None:
                        continue
                    created.append(
                        ScheduleOccurrence(
                            occurrence_id=occurrence_id,
                            schedule_id=schedule.id,
                            schedule_revision_id=revision.id,
                            occurrence_key=occurrence_key,
                            local_wall_time=naive,
                            scheduled_at=as_utc,
                            fold=0,
                            state=state,
                            reason=reason,
                            run_id=None,
                        )
                    )
                grace = timedelta(minutes=content.catch_up_grace_minutes)
                await session.execute(
                    sa.update(tables.schedule_occurrences)
                    .where(
                        tables.schedule_occurrences.c.schedule_revision_id == revision.id,
                        tables.schedule_occurrences.c.state == "pending",
                        tables.schedule_occurrences.c.scheduled_at.is_not(None),
                        tables.schedule_occurrences.c.scheduled_at < moment - grace,
                    )
                    .values(state="missed", reason="downtime", updated_at=sa.func.now())
                )
        return created

    async def _active_run_exists(self, session, schedule_id: UUID) -> bool:
        active = (
            await session.execute(
                sa.select(tables.schedule_occurrences.c.run_id).where(
                    tables.schedule_occurrences.c.schedule_id == schedule_id,
                    tables.schedule_occurrences.c.state == "claimed",
                    tables.schedule_occurrences.c.run_id.is_not(None),
                )
            )
        ).all()
        run_ids = [row.run_id for row in active if row.run_id is not None]
        if not run_ids:
            return False
        non_terminal = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.runs)
                .where(tables.runs.c.id.in_(run_ids), tables.runs.c.status.not_in(TERMINAL_RUN_STATUSES))
            )
        ).scalar_one()
        return int(non_terminal) > 0

    async def claim_due(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        worker_id: str,
        actor: str = "scheduler",
        now: datetime | None = None,
        limit: int = 10,
    ) -> list[ScheduleOccurrence]:
        moment = now or self.now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        claimed: list[ScheduleOccurrence] = []
        candidates: list[Any] = []
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.schedule_occurrences)
                    .join(tables.schedules, tables.schedules.c.id == tables.schedule_occurrences.c.schedule_id)
                    .where(
                        tables.schedule_occurrences.c.workspace_id == workspace_id,
                        tables.schedules.c.enabled.is_(True),
                        tables.schedule_occurrences.c.state.in_(("pending", "queued")),
                        tables.schedule_occurrences.c.scheduled_at.is_not(None),
                        tables.schedule_occurrences.c.scheduled_at <= moment,
                    )
                    .order_by(tables.schedule_occurrences.c.scheduled_at, tables.schedule_occurrences.c.id)
                    .limit(limit)
                )
            ).all()
            for row in rows:
                if await self._active_run_exists(session, row.schedule_id):
                    if row.state == "pending":
                        revision_content = (
                            await session.execute(
                                sa.select(tables.schedule_revisions.c.content).where(
                                    tables.schedule_revisions.c.id == row.schedule_revision_id
                                )
                            )
                        ).scalar_one()
                        overlap = validate_schedule_content(revision_content).overlap
                        if overlap == "queue":
                            await session.execute(
                                sa.update(tables.schedule_occurrences)
                                .where(
                                    tables.schedule_occurrences.c.id == row.id,
                                    tables.schedule_occurrences.c.state == "pending",
                                )
                                .values(state="queued", reason="overlap_queue", updated_at=sa.func.now())
                            )
                        else:
                            await session.execute(
                                sa.update(tables.schedule_occurrences)
                                .where(
                                    tables.schedule_occurrences.c.id == row.id,
                                    tables.schedule_occurrences.c.state == "pending",
                                )
                                .values(state="skipped", reason="overlap_skip", updated_at=sa.func.now())
                            )
                    continue
                result = (
                    await session.execute(
                        sa.update(tables.schedule_occurrences)
                        .where(
                            tables.schedule_occurrences.c.id == row.id,
                            tables.schedule_occurrences.c.state == row.state,
                        )
                        .values(
                            state="claimed",
                            claimed_by=worker_id,
                            claim_epoch=row.claim_epoch + 1,
                            reason=None,
                            updated_at=sa.func.now(),
                        )
                        .returning(tables.schedule_occurrences.c.id)
                    )
                ).scalar_one_or_none()
                if result is not None:
                    candidates.append(
                        (row, row.state, validate_schedule_content(await self._revision_content(session, row)))
                    )
        for row, _previous_state, content in candidates:
            occurrence, run_id = await self._dispatch(
                workspace_id=workspace_id,
                principal_id=principal_id,
                actor=actor,
                row=row,
                content=content,
            )
            claimed.append(occurrence)
            _ = run_id
        return claimed

    async def _revision_content(self, session, row: Any) -> dict:
        return (
            await session.execute(
                sa.select(tables.schedule_revisions.c.content).where(
                    tables.schedule_revisions.c.id == row.schedule_revision_id
                )
            )
        ).scalar_one()

    async def _dispatch(
        self, *, workspace_id: UUID, principal_id: UUID, actor: str, row: Any, content: ScheduleContent
    ) -> tuple[ScheduleOccurrence, UUID | None]:
        try:
            outcome = await self._runs.submit(
                SubmitRequest(
                    workspace_id=workspace_id,
                    principal_id=principal_id,
                    actor=actor,
                    idempotency_key=f"schedule:{row.occurrence_key}",
                    suite_revision_id=content.suite_revision_id,
                    environment_revision_id=content.environment_revision_id,
                )
            )
        except Exception as error:
            async with self._factory() as session, session.begin():
                await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                await session.execute(
                    sa.update(tables.schedule_occurrences)
                    .where(tables.schedule_occurrences.c.id == row.id)
                    .values(state="skipped", reason=f"dispatch_failed:{type(error).__name__}", updated_at=sa.func.now())
                )
            return (
                ScheduleOccurrence(
                    occurrence_id=row.id,
                    schedule_id=row.schedule_id,
                    schedule_revision_id=row.schedule_revision_id,
                    occurrence_key=row.occurrence_key,
                    local_wall_time=row.local_wall_time,
                    scheduled_at=row.scheduled_at,
                    fold=row.fold,
                    state="skipped",
                    reason=f"dispatch_failed:{type(error).__name__}",
                    run_id=None,
                ),
                None,
            )
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.update(tables.schedule_occurrences)
                .where(tables.schedule_occurrences.c.id == row.id)
                .values(run_id=outcome.run_id, updated_at=sa.func.now())
            )
        return (
            ScheduleOccurrence(
                occurrence_id=row.id,
                schedule_id=row.schedule_id,
                schedule_revision_id=row.schedule_revision_id,
                occurrence_key=row.occurrence_key,
                local_wall_time=row.local_wall_time,
                scheduled_at=row.scheduled_at,
                fold=row.fold,
                state="claimed",
                reason=None,
                run_id=outcome.run_id,
            ),
            outcome.run_id,
        )
