from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentqa.platform.storage.scope import set_scope
from agentqa.platform.storage.tables import action_commands, browser_sessions
from agentqa.platform.supervisor.commands import CommandState
from agentqa.platform.supervisor.journal import CommandJournal

RECOVERY_UNKNOWN_REASON = "owner_lost_reconciliation"


class RecoveryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconcileReport:
    unknown_command_ids: list[UUID] = field(default_factory=list)
    quarantined_sessions: list[str] = field(default_factory=list)
    reconciled: bool = True


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str


class RecoveryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        journal: CommandJournal,
        *,
        workspace_id: UUID,
        principal_id: UUID,
    ) -> None:
        self._factory = session_factory
        self._journal = journal
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

    async def reconcile_attempt(self, attempt_id: UUID) -> ReconcileReport:
        unknown: list[UUID] = []
        quarantined: list[str] = []
        try:
            async with self._transaction() as session:
                pending_commands = (
                    await session.execute(
                        sa.select(action_commands.c.command_id, action_commands.c.fence_epoch).where(
                            action_commands.c.workspace_id == self._workspace_id,
                            action_commands.c.attempt_id == attempt_id,
                            action_commands.c.state.in_((CommandState.ACCEPTED.value, CommandState.DISPATCHED.value)),
                        )
                    )
                ).all()
                open_sessions = (
                    await session.execute(
                        sa.select(browser_sessions.c.session_key).where(
                            browser_sessions.c.workspace_id == self._workspace_id,
                            browser_sessions.c.attempt_id == attempt_id,
                            browser_sessions.c.state.in_(("open", "closing")),
                        )
                    )
                ).all()
                quarantined = [row.session_key for row in open_sessions]
            for command in pending_commands:
                try:
                    await self._journal.mark_unknown(
                        command.command_id,
                        fence_epoch=command.fence_epoch,
                        reason=RECOVERY_UNKNOWN_REASON,
                    )
                    unknown.append(command.command_id)
                except Exception:
                    continue
            for session_key in quarantined:
                try:
                    await self._journal.close_session(session_key, reason="owner_lost", quarantine=True)
                except Exception:
                    continue
            return ReconcileReport(unknown_command_ids=unknown, quarantined_sessions=quarantined)
        except SQLAlchemyError as exc:
            raise RecoveryUnavailable(str(exc)) from exc

    async def retry_decision(self, attempt_id: UUID, *, fixture_reset_ok: bool) -> RetryDecision:
        try:
            async with self._transaction() as session:
                unresolved = (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(action_commands)
                        .where(
                            action_commands.c.workspace_id == self._workspace_id,
                            action_commands.c.attempt_id == attempt_id,
                            action_commands.c.state == CommandState.UNKNOWN.value,
                        )
                    )
                ).scalar_one()
            if unresolved and not fixture_reset_ok:
                return RetryDecision(
                    allowed=False,
                    reason="unknown chưa được reconcile; cần fixture reset receipt trước khi retry",
                )
            return RetryDecision(allowed=True, reason="ok")
        except SQLAlchemyError as exc:
            raise RecoveryUnavailable(str(exc)) from exc
