from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentqa.platform.storage.scope import set_scope
from agentqa.platform.storage.tables import run_controls

CONTROL_ACTIONS = frozenset({"pause", "resume", "cancel"})


class ControlUnavailable(RuntimeError):
    pass


class UnknownControlAction(ValueError):
    pass


@dataclass(frozen=True)
class ControlRecord:
    id: UUID
    run_id: UUID
    action: str
    requested_by: str
    requested_at: datetime
    effective_at: datetime | None
    effective_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_id": str(self.id),
            "run_id": str(self.run_id),
            "action": self.action,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at.isoformat(),
            "effective_at": self.effective_at.isoformat() if self.effective_at else None,
            "effective_reason": self.effective_reason,
        }


class ControlService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workspace_id: UUID,
        principal_id: UUID,
    ) -> None:
        self._factory = session_factory
        self._workspace_id = workspace_id
        self._principal_id = principal_id

    def _transaction(self) -> Any:
        factory = self._factory
        principal_id = self._principal_id
        workspace_id = self._workspace_id

        class _Scope:
            async def __aenter__(self) -> AsyncSession:
                self._session = factory()
                await self._session.__aenter__()
                self._begin = self._session.begin()
                await self._begin.__aenter__()
                await set_scope(self._session, principal_id=principal_id, workspace_id=workspace_id)
                return self._session

            async def __aexit__(self, *exc_info: object) -> Any:
                try:
                    return await self._begin.__aexit__(*exc_info)
                finally:
                    await self._session.__aexit__(*exc_info)

        return _Scope()

    async def request(
        self,
        *,
        run_id: UUID,
        action: str,
        requested_by: str,
        reason: str | None = None,
    ) -> ControlRecord:
        if action not in CONTROL_ACTIONS:
            raise UnknownControlAction(action)
        try:
            async with self._transaction() as session:
                pending = (
                    await session.execute(
                        sa.select(run_controls)
                        .where(
                            run_controls.c.workspace_id == self._workspace_id,
                            run_controls.c.run_id == run_id,
                            run_controls.c.action == action,
                            run_controls.c.effective_at.is_(None),
                        )
                        .order_by(run_controls.c.requested_at.desc(), run_controls.c.id.desc())
                        .limit(1)
                    )
                ).first()
                if pending is not None:
                    return self._record(pending)
                row = (
                    await session.execute(
                        sa.insert(run_controls)
                        .values(
                            workspace_id=self._workspace_id,
                            run_id=run_id,
                            action=action,
                            requested_by=requested_by,
                            reason=reason,
                        )
                        .returning(run_controls)
                    )
                ).one()
                return self._record(row)
        except SQLAlchemyError as exc:
            raise ControlUnavailable(str(exc)) from exc

    async def mark_effective(self, control_id: UUID, *, reason: str) -> ControlRecord:
        try:
            async with self._transaction() as session:
                await session.execute(
                    sa.update(run_controls)
                    .where(
                        run_controls.c.workspace_id == self._workspace_id,
                        run_controls.c.id == control_id,
                        run_controls.c.effective_at.is_(None),
                    )
                    .values(effective_at=sa.func.now(), effective_reason=reason)
                )
                row = (
                    await session.execute(
                        sa.select(run_controls).where(
                            run_controls.c.workspace_id == self._workspace_id,
                            run_controls.c.id == control_id,
                        )
                    )
                ).one()
                return self._record(row)
        except SQLAlchemyError as exc:
            raise ControlUnavailable(str(exc)) from exc

    async def latest(self, run_id: UUID) -> ControlRecord | None:
        try:
            async with self._transaction() as session:
                row = (
                    await session.execute(
                        sa.select(run_controls)
                        .where(
                            run_controls.c.workspace_id == self._workspace_id,
                            run_controls.c.run_id == run_id,
                        )
                        .order_by(run_controls.c.requested_at.desc(), run_controls.c.id.desc())
                        .limit(1)
                    )
                ).first()
                return None if row is None else self._record(row)
        except SQLAlchemyError as exc:
            raise ControlUnavailable(str(exc)) from exc

    def _record(self, row: Any) -> ControlRecord:
        return ControlRecord(
            id=row.id,
            run_id=row.run_id,
            action=row.action,
            requested_by=row.requested_by,
            requested_at=row.requested_at,
            effective_at=row.effective_at,
            effective_reason=row.effective_reason,
        )
