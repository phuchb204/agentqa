from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


class HealingService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def list_for_run(
        self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID
    ) -> list[dict[str, Any]] | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            run = (
                await session.execute(
                    sa.select(tables.runs.c.id).where(
                        tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id
                    )
                )
            ).one_or_none()
            if run is None:
                return None
            rows = (
                await session.execute(
                    sa.select(tables.healing_records)
                    .where(
                        tables.healing_records.c.workspace_id == workspace_id,
                        tables.healing_records.c.run_id == run_id,
                    )
                    .order_by(tables.healing_records.c.recorded_at, tables.healing_records.c.id)
                )
            ).all()
        return [
            {
                "record_id": row.id,
                "run_id": row.run_id,
                "execution_id": row.execution_id,
                "attempt_id": row.attempt_id,
                "actor": row.actor,
                "node_id": row.node_id,
                "opportunity_id": row.opportunity_id,
                "attempt_ref": row.attempt_ref,
                "decision": row.decision,
                "ranking": row.ranking,
                "expected_signature": row.expected_signature,
                "actual_signature": row.actual_signature,
                "original_target": row.original_target,
                "actual_target": row.actual_target,
                "dispatch_outcome": row.dispatch_outcome,
                "guard_checks": list(row.guard_checks or []),
                "postconditions_ok": row.postconditions_ok,
                "refusal_reason": row.refusal_reason,
                "error": row.error,
                "proposal": row.proposal,
                "source_run_id": row.source_run_id,
                "case_id": row.case_id,
                "case_revision_id": row.case_revision_id,
                "recorded_at": row.recorded_at,
            }
            for row in rows
        ]
