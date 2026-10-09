from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.runs import TERMINAL_STATUSES
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

TERMINAL_VALUES = {item.value for item in TERMINAL_STATUSES}


class RunReadModel:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def run_state(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            run = (
                await session.execute(
                    sa.select(tables.runs).where(tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id)
                )
            ).one_or_none()
            if run is None:
                return None
            executions = (
                await session.execute(
                    sa.select(
                        tables.executions.c.id,
                        tables.executions.c.logical_key,
                        tables.executions.c.status,
                        tables.executions.c.verdict,
                    )
                    .where(tables.executions.c.run_id == run_id)
                    .order_by(tables.executions.c.created_at, tables.executions.c.id)
                )
            ).all()
            controls = (
                await session.execute(
                    sa.select(tables.run_controls)
                    .where(tables.run_controls.c.run_id == run_id)
                    .order_by(tables.run_controls.c.requested_at, tables.run_controls.c.id)
                )
            ).all()
            last_run_seq = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.max(tables.run_events.c.run_seq), 0)).where(
                        tables.run_events.c.run_id == run_id
                    )
                )
            ).scalar_one()
            snapshot_digest = (
                await session.execute(
                    sa.select(tables.run_snapshots.c.content_digest).where(tables.run_snapshots.c.run_id == run_id)
                )
            ).scalar_one_or_none()
        return {
            "run_id": run.id,
            "status": run.status,
            "verdict": run.verdict,
            "gate": run.gate,
            "reasons": list(run.reasons or []),
            "snapshot_digest": snapshot_digest,
            "last_run_seq": int(last_run_seq),
            "executions": [
                {
                    "execution_id": row.id,
                    "logical_key": row.logical_key,
                    "status": row.status,
                    "verdict": row.verdict,
                }
                for row in executions
            ],
            "controls": [
                {
                    "control_id": row.id,
                    "action": row.action,
                    "requested_at": row.requested_at,
                    "effective_at": row.effective_at,
                    "effective_reason": row.effective_reason,
                }
                for row in controls
            ],
        }

    async def run_result(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        state = await self.run_state(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)
        if state is None:
            return None
        return {
            "run_id": state["run_id"],
            "status": state["status"],
            "verdict": state["verdict"],
            "gate": state["gate"],
            "reasons": state["reasons"],
            "terminal": state["status"] in TERMINAL_VALUES,
            "executions": state["executions"],
        }
