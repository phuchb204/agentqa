from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.repositories import SequenceRepository
from agentqa.platform.storage.scope import set_scope

NOTIFY_CHANNEL = "agentqa_run_events"


def current_payload_month() -> date:
    today = datetime.now(UTC).date()
    return today.replace(day=1)


@dataclass(frozen=True)
class AppendedEvent:
    event_id: UUID
    run_id: UUID
    run_seq: int
    execution_id: UUID | None
    execution_seq: int | None
    payload_month: date
    recorded_at: datetime


class EventService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def append(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        run_id: UUID,
        event_type: str,
        actor: str,
        payload: dict | None = None,
        phase: str | None = None,
        execution_id: UUID | None = None,
        payload_doc: dict | None = None,
        recorded_at: datetime | None = None,
    ) -> AppendedEvent:
        run_row = (
            await session.execute(
                sa.select(tables.runs.c.id)
                .where(tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id)
                .with_for_update()
            )
        ).one_or_none()
        if run_row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy run trong scope")

        sequences = SequenceRepository(session)
        run_seq = await sequences.allocate_run_seq(run_id)
        execution_seq: int | None = None
        if execution_id is not None:
            execution_row = (
                await session.execute(
                    sa.select(tables.executions.c.id)
                    .where(
                        tables.executions.c.workspace_id == workspace_id,
                        tables.executions.c.id == execution_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if execution_row is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy execution trong scope")
            execution_seq = await sequences.allocate_execution_seq(execution_id)

        event_id = uuid4()
        month = current_payload_month()
        moment = recorded_at or datetime.now(UTC)
        await session.execute(
            sa.insert(tables.run_events).values(
                id=event_id,
                workspace_id=workspace_id,
                run_id=run_id,
                run_seq=run_seq,
                execution_id=execution_id,
                execution_seq=execution_seq,
                type=event_type,
                phase=phase,
                actor=actor,
                summary=payload or {},
                payload_month=month,
                recorded_at=moment,
            )
        )
        if payload_doc is not None:
            await session.execute(
                sa.insert(tables.run_event_payloads).values(event_id=event_id, payload_month=month, payload=payload_doc)
            )
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": NOTIFY_CHANNEL, "payload": f"{run_id}:{run_seq}"},
        )
        return AppendedEvent(
            event_id=event_id,
            run_id=run_id,
            run_seq=run_seq,
            execution_id=execution_id,
            execution_seq=execution_seq,
            payload_month=month,
            recorded_at=moment,
        )

    async def enqueue_outbox(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        topic: str,
        dedupe_key: str,
        payload: dict | None = None,
    ) -> UUID:
        outbox_id = (
            await session.execute(
                sa.insert(tables.outbox_deliveries)
                .values(
                    workspace_id=workspace_id,
                    topic=topic,
                    dedupe_key=dedupe_key,
                    payload=payload or {},
                )
                .returning(tables.outbox_deliveries.c.id)
            )
        ).scalar_one()
        return outbox_id

    async def query_durable(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_id: UUID,
        after_run_seq: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(
                        tables.run_events.c.id.label("event_id"),
                        tables.run_events.c.run_seq,
                        tables.run_events.c.execution_id,
                        tables.run_events.c.execution_seq,
                        tables.run_events.c.type,
                        tables.run_events.c.payload_month,
                        tables.run_events.c.summary,
                    )
                    .where(
                        tables.run_events.c.workspace_id == workspace_id,
                        tables.run_events.c.run_id == run_id,
                        tables.run_events.c.run_seq > after_run_seq,
                    )
                    .order_by(tables.run_events.c.run_seq)
                    .limit(min(limit, 500))
                )
            ).all()
        return [
            {
                "event_id": row.event_id,
                "run_seq": row.run_seq,
                "execution_id": row.execution_id,
                "execution_seq": row.execution_seq,
                "type": row.type,
                "payload_month": row.payload_month,
                "summary": row.summary,
            }
            for row in rows
        ]
