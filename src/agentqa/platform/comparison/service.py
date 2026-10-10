from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


class ComparisonService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._factory = create_session_factory(engine)

    async def compare(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_a: UUID,
        run_b: UUID,
    ) -> dict[str, Any] | None:
        base = await RunReadModel(self._engine).run_comparison(
            workspace_id=workspace_id, principal_id=principal_id, run_a=run_a, run_b=run_b
        )
        if base is None:
            return None
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            denominators = {
                "a": await self._denominators(session, workspace_id=workspace_id, run_id=run_a),
                "b": await self._denominators(session, workspace_id=workspace_id, run_id=run_b),
            }
            provenance = {
                "a": await self._provenance(session, workspace_id=workspace_id, run_id=run_a),
                "b": await self._provenance(session, workspace_id=workspace_id, run_id=run_b),
            }
        return {**base, "denominators": denominators, "provenance": provenance}

    async def _denominators(self, session, *, workspace_id: UUID, run_id: UUID) -> dict[str, Any]:
        executions = (
            (
                await session.execute(
                    sa.select(tables.executions.c.status).where(
                        tables.executions.c.workspace_id == workspace_id, tables.executions.c.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        calls = (
            (
                await session.execute(
                    sa.select(tables.model_calls.c.record_state).where(
                        tables.model_calls.c.workspace_id == workspace_id, tables.model_calls.c.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        costs = (
            await session.execute(
                sa.select(tables.cost_entries.c.record_state, tables.cost_entries.c.coverage).where(
                    tables.cost_entries.c.workspace_id == workspace_id, tables.cost_entries.c.run_id == run_id
                )
            )
        ).all()
        terminal = {"succeeded", "failed", "cancelled", "inconclusive", "error"}
        return {
            "executions_total": len(executions),
            "executions_terminal": sum(1 for status in executions if status in terminal),
            "calls_total": len(calls),
            "calls_settled": sum(1 for state in calls if state == "settled"),
            "calls_unknown": sum(1 for state in calls if state != "settled"),
            "cost_entries": len(costs),
            "cost_entries_complete": sum(
                1 for row in costs if row.record_state == "settled" and row.coverage == "complete"
            ),
        }

    async def _provenance(self, session, *, workspace_id: UUID, run_id: UUID) -> dict[str, Any]:
        row = (
            await session.execute(
                sa.select(tables.run_snapshots.c.content, tables.run_snapshots.c.content_digest).where(
                    tables.run_snapshots.c.workspace_id == workspace_id, tables.run_snapshots.c.run_id == run_id
                )
            )
        ).one_or_none()
        if row is None:
            return {}
        content = row.content or {}
        return {
            "snapshot_digest": row.content_digest,
            "policy": content.get("policy"),
            "observation_mode": content.get("observation_mode"),
            "gate_profile": content.get("gate_profile"),
            "cache_profile": content.get("cache_profile"),
            "calibration_ref": content.get("calibration_ref"),
        }
