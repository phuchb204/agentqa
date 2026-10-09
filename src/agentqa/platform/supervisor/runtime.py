from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from pydantic import TypeAdapter

from agentqa.contracts.actions import ActionCommand, ActionOutcome, ActionReceipt
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import ValueExpr
from agentqa.platform.supervisor.commands import CommandReceiptRecord, CommandRequest, CommandState
from agentqa.platform.supervisor.journal import JournalUnavailable, SessionNotOpen

VALUE_ADAPTER = TypeAdapter(ValueExpr)


class ActionExecutor(Protocol):
    async def dispatch(self, command: ActionCommand) -> ActionReceipt: ...


@dataclass(frozen=True)
class RuntimeConfig:
    supervisor_id: str
    fence_epoch: int = 1
    lease_seconds: float = 30.0
    control_wait_seconds: float = 5.0


@dataclass
class SessionRuntime:
    view: dict[str, Any]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inflight_command: UUID | None = None
    last_heartbeat: float = field(default_factory=time.monotonic)


class SupervisorRuntime:
    def __init__(
        self,
        journal: Any,
        executor: ActionExecutor,
        config: RuntimeConfig,
    ) -> None:
        self._journal = journal
        self._executor = executor
        self._config = config
        self._sessions: dict[str, SessionRuntime] = {}

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def journal(self) -> Any:
        return self._journal

    async def receipts(self, attempt_id: UUID) -> list[dict[str, Any]]:
        return [record.as_dict() for record in await self._journal.receipts(attempt_id)]

    async def session_view(self, session_key: str) -> dict[str, Any] | None:
        return await self._journal.session_view(session_key)

    async def open_session(
        self,
        *,
        run_id: UUID,
        attempt_id: UUID,
        session_key: str,
        fence_epoch: int,
        scene_version: int = 1,
    ) -> dict[str, Any]:
        view = await self._journal.open_session(
            run_id=run_id,
            attempt_id=attempt_id,
            session_key=session_key,
            fence_epoch=fence_epoch,
            scene_version=scene_version,
        )
        self._sessions.setdefault(session_key, SessionRuntime(view=view))
        return view

    async def execute(self, request: CommandRequest) -> CommandReceiptRecord:
        try:
            prepared = await self._journal.prepare(request)
        except JournalUnavailable:
            return _local_receipt(request, CommandState.REJECTED, "rejected", "db_unavailable")
        except SessionNotOpen:
            return _local_receipt(request, CommandState.REJECTED, "rejected", "session_not_open")
        if prepared.state != CommandState.PREPARED.value:
            return prepared
        session = self._sessions.get(request.session_key)
        if session is None:
            return _local_receipt(request, CommandState.REJECTED, "rejected", "session_not_registered")
        async with session.lock:
            try:
                admitted = await self._journal.admit(
                    request.command_id,
                    fence_epoch=request.fence_epoch,
                    control_revision=request.control_revision,
                    expected_observation_version=request.expected_observation_version,
                )
            except JournalUnavailable:
                return _local_receipt(request, CommandState.REJECTED, "rejected", "db_unavailable")
            if admitted.state != CommandState.ACCEPTED.value:
                return admitted
            try:
                await self._journal.mark_dispatched(request.command_id, fence_epoch=request.fence_epoch)
            except JournalUnavailable:
                return _local_receipt(request, CommandState.REJECTED, "rejected", "db_unavailable_pre_dispatch")
            except Exception as exc:
                return await self._journal.mark_unknown(
                    request.command_id,
                    fence_epoch=request.fence_epoch,
                    reason=f"dispatch_record_error:{type(exc).__name__}",
                )
            session.inflight_command = request.command_id
            try:
                receipt = await self._executor.dispatch(self._action_command(request))
            except Exception as exc:
                return await self._mark_unknown(request, f"executor_error:{type(exc).__name__}")
            finally:
                session.inflight_command = None
            evidence = list(receipt.evidence_refs)
            if receipt.outcome == ActionOutcome.SUCCEEDED:
                return await self._journal.settle(
                    request.command_id, fence_epoch=request.fence_epoch, outcome="succeeded", evidence=evidence
                )
            if receipt.outcome == ActionOutcome.UNKNOWN:
                return await self._journal.mark_unknown(
                    request.command_id, fence_epoch=request.fence_epoch, reason="outcome_unknown"
                )
            return await self._journal.settle(
                request.command_id,
                fence_epoch=request.fence_epoch,
                outcome="failed",
                evidence=evidence or ["action_failed"],
                reason="action_failed",
            )

    async def heartbeat(self, session_key: str) -> bool:
        session = self._sessions.get(session_key)
        try:
            alive = await self._journal.heartbeat(session_key)
        except JournalUnavailable:
            return False
        if alive and session is not None:
            session.last_heartbeat = time.monotonic()
        return alive

    async def close_session(self, session_key: str, *, reason: str, quarantine: bool = False) -> dict[str, Any]:
        self._sessions.pop(session_key, None)
        return await self._journal.close_session(session_key, reason=reason, quarantine=quarantine)

    async def apply_control(self, control_id: UUID, *, reason: str = "barrier_applied") -> dict[str, Any]:
        uncertain: list[UUID] = []
        for session in list(self._sessions.values()):
            acquired = False
            try:
                await asyncio.wait_for(session.lock.acquire(), timeout=self._config.control_wait_seconds)
                acquired = True
            except TimeoutError:
                if session.inflight_command is not None:
                    command_id = session.inflight_command
                    with contextlib.suppress(Exception):
                        await self._journal.mark_unknown(
                            command_id,
                            fence_epoch=self._config.fence_epoch,
                            reason="cancel_bound_exceeded",
                        )
                    uncertain.append(command_id)
            finally:
                if acquired:
                    session.lock.release()
        await self._journal.mark_control_effective(control_id, reason=reason)
        return {"effective": True, "uncertain_commands": [str(item) for item in uncertain]}

    async def monitor(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.2)
            now = time.monotonic()
            for session_key, session in list(self._sessions.items()):
                if now - session.last_heartbeat > self._config.lease_seconds:
                    with contextlib.suppress(Exception):
                        await self.close_session(session_key, reason="lease_lost", quarantine=True)

    async def _mark_unknown(self, request: CommandRequest, reason: str) -> CommandReceiptRecord:
        try:
            return await self._journal.mark_unknown(request.command_id, fence_epoch=request.fence_epoch, reason=reason)
        except JournalUnavailable:
            return _local_receipt(request, CommandState.UNKNOWN, "unknown", "db_unavailable_after_dispatch")

    def _action_command(self, request: CommandRequest) -> ActionCommand:
        payload = request.payload
        target = TargetDescriptor.model_validate(payload["target"]) if payload.get("target") else None
        value = VALUE_ADAPTER.validate_python(payload["value"]) if payload.get("value") is not None else None
        return ActionCommand(
            command_id=request.command_id,
            run_id=request.run_id,
            attempt_id=request.attempt_id,
            fence_epoch=request.fence_epoch,
            expected_observation_version=request.expected_observation_version,
            operation=request.operation,
            target=target,
            value=value,
            secret_grant_refs=list(payload.get("secret_grant_refs", [])),
        )


def _local_receipt(request: CommandRequest, state: CommandState, outcome: str, reason: str) -> CommandReceiptRecord:
    return CommandReceiptRecord(
        command_id=request.command_id,
        session_id=None,
        state=state.value,
        outcome=outcome,
        fence_epoch=request.fence_epoch,
        input_digest="",
        evidence=[reason],
        reason=reason,
    )
