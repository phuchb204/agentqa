from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentqa.contracts.canonical import digest_content
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.storage.tables import action_commands, browser_sessions, command_receipts, run_controls
from agentqa.platform.supervisor.commands import CommandReceiptRecord, CommandRequest, CommandState


class JournalUnavailable(RuntimeError):
    pass


class SessionNotOpen(RuntimeError):
    pass


class StaleFence(RuntimeError):
    def __init__(self, command_id: UUID) -> None:
        self.command_id = command_id
        super().__init__(f"fence stale cho command {command_id}")


class CommandJournal:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workspace_id: UUID,
        principal_id: UUID,
        supervisor_id: str,
    ) -> None:
        self._factory = session_factory
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._supervisor_id = supervisor_id

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

    async def open_session(
        self,
        *,
        run_id: UUID,
        attempt_id: UUID,
        session_key: str,
        fence_epoch: int,
        scene_version: int = 1,
    ) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                insert = (
                    postgresql.insert(browser_sessions)
                    .values(
                        workspace_id=self._workspace_id,
                        run_id=run_id,
                        attempt_id=attempt_id,
                        session_key=session_key,
                        supervisor_id=self._supervisor_id,
                        fence_epoch=fence_epoch,
                        scene_version=scene_version,
                        state="open",
                    )
                    .on_conflict_do_nothing(index_elements=["workspace_id", "session_key"])
                )
                await session.execute(insert)
                row = await self._session_row(session, session_key, lock=False)
                return self._session_view(row)
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def session_view(self, session_key: str) -> dict[str, Any] | None:
        try:
            async with self._transaction() as session:
                row = await self._session_row(session, session_key, lock=False)
                return None if row is None else self._session_view(row)
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def prepare(self, request: CommandRequest) -> CommandReceiptRecord:
        try:
            async with self._transaction() as session:
                existing = await self._command_row(session, request.command_id, lock=False)
                if existing is not None:
                    return await self._latest_receipt(session, request.command_id, existing)
                session_row = await self._session_row(session, request.session_key, lock=True)
                if session_row is None or session_row.state != "open":
                    raise SessionNotOpen(request.session_key)
                digest = self._input_digest(request)
                await session.execute(
                    sa.insert(action_commands).values(
                        workspace_id=self._workspace_id,
                        run_id=request.run_id,
                        attempt_id=request.attempt_id,
                        session_id=session_row.id,
                        command_id=request.command_id,
                        fence_epoch=request.fence_epoch,
                        expected_observation_version=request.expected_observation_version,
                        control_revision=request.control_revision,
                        operation=request.operation.value,
                        payload_digest=digest,
                        payload=request.payload,
                        state=CommandState.PREPARED.value,
                        side_effect=request.side_effect,
                    )
                )
                row = await self._command_row(session, request.command_id, lock=False)
                return self._prepared_receipt(row)
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def admit(
        self,
        command_id: UUID,
        *,
        fence_epoch: int,
        control_revision: int,
        expected_observation_version: int,
    ) -> CommandReceiptRecord:
        try:
            async with self._transaction() as session:
                command = await self._command_row(session, command_id, lock=True)
                assert command is not None
                if command.state in (
                    CommandState.ACCEPTED.value,
                    CommandState.DISPATCHED.value,
                    CommandState.SETTLED.value,
                    CommandState.UNKNOWN.value,
                ):
                    return await self._latest_receipt(session, command_id, command)
                if command.state == CommandState.REJECTED.value:
                    return await self._receipt_for_state(session, command_id, CommandState.REJECTED.value)
                session_row = await self._session_row_by_id(session, command.session_id, lock=True)
                reason = await self._admission_reason(
                    session,
                    command,
                    session_row,
                    fence_epoch=fence_epoch,
                    control_revision=control_revision,
                    expected_observation_version=expected_observation_version,
                )
                if reason is not None:
                    await session.execute(
                        sa.update(action_commands)
                        .where(
                            action_commands.c.workspace_id == self._workspace_id,
                            action_commands.c.command_id == command_id,
                        )
                        .values(state=CommandState.REJECTED.value, reject_reason=reason, updated_at=sa.func.now())
                    )
                    return await self._insert_receipt(
                        session,
                        command_id=command_id,
                        session_id=command.session_id,
                        state=CommandState.REJECTED.value,
                        outcome="rejected",
                        fence_epoch=command.fence_epoch,
                        input_digest=command.payload_digest,
                        evidence=[reason],
                        reason=reason,
                    )
                await session.execute(
                    sa.update(action_commands)
                    .where(
                        action_commands.c.workspace_id == self._workspace_id,
                        action_commands.c.command_id == command_id,
                    )
                    .values(state=CommandState.ACCEPTED.value, updated_at=sa.func.now())
                )
                return await self._insert_receipt(
                    session,
                    command_id=command_id,
                    session_id=command.session_id,
                    state=CommandState.ACCEPTED.value,
                    outcome="unknown",
                    fence_epoch=command.fence_epoch,
                    input_digest=command.payload_digest,
                    evidence=[],
                    reason=None,
                )
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def mark_dispatched(self, command_id: UUID, *, fence_epoch: int) -> CommandReceiptRecord:
        return await self._transition(
            command_id,
            fence_epoch=fence_epoch,
            from_states=(CommandState.ACCEPTED.value,),
            to_state=CommandState.DISPATCHED.value,
            outcome="unknown",
            evidence=[],
            reason=None,
            terminal="dispatched",
        )

    async def settle(
        self,
        command_id: UUID,
        *,
        fence_epoch: int,
        outcome: str,
        evidence: list[str],
        reason: str | None = None,
    ) -> CommandReceiptRecord:
        return await self._transition(
            command_id,
            fence_epoch=fence_epoch,
            from_states=(CommandState.DISPATCHED.value,),
            to_state=CommandState.SETTLED.value,
            outcome=outcome,
            evidence=evidence,
            reason=reason,
            terminal="settled",
        )

    async def mark_unknown(self, command_id: UUID, *, fence_epoch: int, reason: str) -> CommandReceiptRecord:
        return await self._transition(
            command_id,
            fence_epoch=fence_epoch,
            from_states=(CommandState.DISPATCHED.value, CommandState.ACCEPTED.value),
            to_state=CommandState.UNKNOWN.value,
            outcome="unknown",
            evidence=[],
            reason=reason,
            terminal="unknown",
        )

    async def heartbeat(self, session_key: str) -> bool:
        try:
            async with self._transaction() as session:
                result = await session.execute(
                    sa.update(browser_sessions)
                    .where(
                        browser_sessions.c.workspace_id == self._workspace_id,
                        browser_sessions.c.session_key == session_key,
                        browser_sessions.c.supervisor_id == self._supervisor_id,
                        browser_sessions.c.state.in_(("open", "closing")),
                    )
                    .values(heartbeat_at=sa.func.now())
                    .returning(browser_sessions.c.id)
                )
                return result.first() is not None
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def close_session(self, session_key: str, *, reason: str, quarantine: bool = False) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                row = await self._session_row(session, session_key, lock=True)
                if row is None:
                    raise SessionNotOpen(session_key)
                state = "quarantined" if quarantine else "closed"
                if row.state not in ("closed", "quarantined"):
                    await session.execute(
                        sa.update(browser_sessions)
                        .where(browser_sessions.c.id == row.id)
                        .values(state=state, closed_reason=reason, closed_at=sa.func.now())
                    )
                refreshed = await self._session_row(session, session_key, lock=False)
                return self._session_view(refreshed)
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def set_scene_version(self, session_key: str, *, scene_version: int) -> None:
        try:
            async with self._transaction() as session:
                await session.execute(
                    sa.update(browser_sessions)
                    .where(
                        browser_sessions.c.workspace_id == self._workspace_id,
                        browser_sessions.c.session_key == session_key,
                    )
                    .values(scene_version=scene_version)
                )
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def mark_control_effective(self, control_id: UUID, *, reason: str) -> None:
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
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def receipts(self, attempt_id: UUID) -> list[CommandReceiptRecord]:
        try:
            async with self._transaction() as session:
                rows = (
                    await session.execute(
                        sa.select(command_receipts)
                        .where(
                            command_receipts.c.workspace_id == self._workspace_id,
                            command_receipts.c.command_id.in_(
                                sa.select(action_commands.c.command_id).where(
                                    action_commands.c.workspace_id == self._workspace_id,
                                    action_commands.c.attempt_id == attempt_id,
                                )
                            ),
                        )
                        .order_by(command_receipts.c.created_at, command_receipts.c.id)
                    )
                ).all()
                return [self._record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def session_snapshots(self, attempt_id: UUID) -> list[dict[str, Any]]:
        try:
            async with self._transaction() as session:
                rows = (
                    await session.execute(
                        sa.select(browser_sessions).where(
                            browser_sessions.c.workspace_id == self._workspace_id,
                            browser_sessions.c.attempt_id == attempt_id,
                        )
                    )
                ).all()
                return [self._session_view(row) for row in rows]
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def _transition(
        self,
        command_id: UUID,
        *,
        fence_epoch: int,
        from_states: tuple[str, ...],
        to_state: str,
        outcome: str,
        evidence: list[str],
        reason: str | None,
        terminal: str,
    ) -> CommandReceiptRecord:
        try:
            async with self._transaction() as session:
                command = await self._command_row(session, command_id, lock=True)
                assert command is not None
                if command.fence_epoch != fence_epoch:
                    raise StaleFence(command_id)
                if command.state in (
                    CommandState.SETTLED.value,
                    CommandState.UNKNOWN.value,
                    CommandState.REJECTED.value,
                ):
                    return await self._latest_receipt(session, command_id, command)
                if command.state not in from_states:
                    return await self._latest_receipt(session, command_id, command)
                await session.execute(
                    sa.update(action_commands)
                    .where(
                        action_commands.c.workspace_id == self._workspace_id,
                        action_commands.c.command_id == command_id,
                    )
                    .values(state=to_state, updated_at=sa.func.now())
                )
                return await self._insert_receipt(
                    session,
                    command_id=command_id,
                    session_id=command.session_id,
                    state=terminal,
                    outcome=outcome,
                    fence_epoch=command.fence_epoch,
                    input_digest=command.payload_digest,
                    evidence=evidence,
                    reason=reason,
                )
        except SQLAlchemyError as exc:
            raise JournalUnavailable(str(exc)) from exc

    async def _admission_reason(
        self,
        session: AsyncSession,
        command: Any,
        session_row: Any,
        *,
        fence_epoch: int,
        control_revision: int,
        expected_observation_version: int,
    ) -> str | None:
        if session_row is None or session_row.state != "open":
            return "session_not_open"
        if session_row.supervisor_id != self._supervisor_id:
            return "owner_mismatch"
        if command.fence_epoch != fence_epoch or session_row.fence_epoch != fence_epoch:
            return "fence_stale"
        if command.control_revision != control_revision or session_row.control_revision != control_revision:
            return "control_revision_stale"
        if (
            command.expected_observation_version != expected_observation_version
            or session_row.scene_version != expected_observation_version
        ):
            return "scene_stale"
        barrier = await self._control_barrier(session, command.run_id)
        if barrier is not None:
            return barrier
        return None

    async def _control_barrier(self, session: AsyncSession, run_id: UUID) -> str | None:
        rows = (
            await session.execute(
                sa.select(run_controls.c.action)
                .where(run_controls.c.workspace_id == self._workspace_id, run_controls.c.run_id == run_id)
                .order_by(run_controls.c.requested_at, run_controls.c.id)
            )
        ).all()
        paused = False
        for row in rows:
            if row.action == "cancel":
                return "control_cancelled"
            if row.action == "pause":
                paused = True
            elif row.action == "resume":
                paused = False
        return "control_paused" if paused else None

    async def _insert_receipt(
        self,
        session: AsyncSession,
        *,
        command_id: UUID,
        session_id: UUID,
        state: str,
        outcome: str,
        fence_epoch: int,
        input_digest: str,
        evidence: list[str],
        reason: str | None,
    ) -> CommandReceiptRecord:
        await session.execute(
            postgresql.insert(command_receipts)
            .values(
                workspace_id=self._workspace_id,
                command_id=command_id,
                session_id=session_id,
                state=state,
                outcome=outcome,
                fence_epoch=fence_epoch,
                input_digest=input_digest,
                evidence=evidence,
                reason=reason,
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "command_id", "state"])
        )
        row = (
            await session.execute(
                sa.select(command_receipts).where(
                    command_receipts.c.workspace_id == self._workspace_id,
                    command_receipts.c.command_id == command_id,
                    command_receipts.c.state == state,
                )
            )
        ).one()
        return self._record(row)

    async def _receipt_for_state(self, session: AsyncSession, command_id: UUID, state: str) -> CommandReceiptRecord:
        row = (
            await session.execute(
                sa.select(command_receipts).where(
                    command_receipts.c.workspace_id == self._workspace_id,
                    command_receipts.c.command_id == command_id,
                    command_receipts.c.state == state,
                )
            )
        ).one()
        return self._record(row)

    async def _latest_receipt(
        self, session: AsyncSession, command_id: UUID, command: Any | None = None
    ) -> CommandReceiptRecord:
        if command is None:
            command = await self._command_row(session, command_id, lock=False)
        assert command is not None
        state_map = {
            CommandState.ACCEPTED.value: CommandState.ACCEPTED.value,
            CommandState.DISPATCHED.value: CommandState.DISPATCHED.value,
            CommandState.SETTLED.value: CommandState.SETTLED.value,
            CommandState.UNKNOWN.value: CommandState.UNKNOWN.value,
            CommandState.REJECTED.value: CommandState.REJECTED.value,
        }
        state = state_map.get(command.state)
        if state is None:
            return self._prepared_receipt(command)
        return await self._receipt_for_state(session, command_id, state)

    async def _command_row(self, session: AsyncSession, command_id: UUID, *, lock: bool) -> Any | None:
        statement = sa.select(action_commands).where(
            action_commands.c.workspace_id == self._workspace_id,
            action_commands.c.command_id == command_id,
        )
        if lock:
            statement = statement.with_for_update()
        return (await session.execute(statement)).first()

    async def _session_row(self, session: AsyncSession, session_key: str, *, lock: bool) -> Any | None:
        statement = sa.select(browser_sessions).where(
            browser_sessions.c.workspace_id == self._workspace_id,
            browser_sessions.c.session_key == session_key,
        )
        if lock:
            statement = statement.with_for_update()
        return (await session.execute(statement)).first()

    async def _session_row_by_id(self, session: AsyncSession, session_id: UUID, *, lock: bool) -> Any | None:
        statement = sa.select(browser_sessions).where(
            browser_sessions.c.workspace_id == self._workspace_id,
            browser_sessions.c.id == session_id,
        )
        if lock:
            statement = statement.with_for_update()
        return (await session.execute(statement)).first()

    def _input_digest(self, request: CommandRequest) -> str:
        return digest_content(
            {
                "operation": request.operation.value,
                "payload": request.payload,
                "expected_observation_version": request.expected_observation_version,
                "control_revision": request.control_revision,
            }
        )

    def _prepared_receipt(self, command: Any) -> CommandReceiptRecord:
        return CommandReceiptRecord(
            command_id=command.command_id,
            session_id=command.session_id,
            state=CommandState.PREPARED.value,
            outcome="unknown",
            fence_epoch=command.fence_epoch,
            input_digest=command.payload_digest,
            evidence=[],
            reason=None,
            recorded_at=command.created_at,
        )

    def _record(self, row: Any) -> CommandReceiptRecord:
        return CommandReceiptRecord(
            command_id=row.command_id,
            session_id=row.session_id,
            state=row.state,
            outcome=row.outcome,
            fence_epoch=row.fence_epoch,
            input_digest=row.input_digest,
            evidence=list(row.evidence or []),
            reason=row.reason,
            recorded_at=row.created_at,
        )

    def _session_view(self, row: Any) -> dict[str, Any]:
        return {
            "session_id": str(row.id),
            "session_key": row.session_key,
            "run_id": str(row.run_id),
            "attempt_id": str(row.attempt_id),
            "supervisor_id": row.supervisor_id,
            "fence_epoch": row.fence_epoch,
            "state": row.state,
            "control_revision": row.control_revision,
            "scene_version": row.scene_version,
            "closed_reason": row.closed_reason,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)
