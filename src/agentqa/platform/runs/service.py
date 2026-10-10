from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import yaml
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_content, digest_run_snapshot
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.observation import Modality
from agentqa.contracts.runs import ControlAction, RunSnapshot
from agentqa.platform.events.service import EventService
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.revisions.service import validate_content
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

SUBMIT_OPERATION = "run.submit"
DRAFT_SUBMIT_OPERATION = "run.submit_draft"


class IdempotencyConflict(IdentityError):
    def __init__(self, message: str = "Idempotency-Key đã dùng với request khác") -> None:
        super().__init__(ErrorCode.INPUT_INVALID, message)
        self.status_code = 409


class ControlConflict(IdentityError):
    def __init__(self, message: str = "Control revision không khớp") -> None:
        super().__init__(ErrorCode.INPUT_INVALID, message)
        self.status_code = 412


class _ConcurrentReplay(Exception):
    pass


@dataclass(frozen=True)
class SubmitRequest:
    workspace_id: UUID
    principal_id: UUID
    actor: str
    idempotency_key: str
    case_revision_ids: tuple[UUID, ...]
    environment_revision_id: UUID | None = None
    policy: str = "default"
    observation_mode: Modality = Modality.SEMANTIC
    budgets: dict[str, int] = field(default_factory=dict)
    cache_profile: str = "default"
    gate_profile: str = "default"
    provided_capabilities: frozenset[str] = frozenset()

    def portable(self) -> dict:
        return {
            "case_revision_ids": [str(item) for item in self.case_revision_ids],
            "environment_revision_id": str(self.environment_revision_id) if self.environment_revision_id else None,
            "policy": self.policy,
            "observation_mode": self.observation_mode.value,
            "budgets": self.budgets,
            "cache_profile": self.cache_profile,
            "gate_profile": self.gate_profile,
            "provided_capabilities": sorted(self.provided_capabilities),
        }


@dataclass(frozen=True)
class DraftSubmitRequest:
    workspace_id: UUID
    principal_id: UUID
    actor: str
    idempotency_key: str
    case_id: UUID
    content: dict
    environment_revision_id: UUID | None = None
    observation_mode: Modality = Modality.SEMANTIC
    gate_profile: str = "strict"
    provided_capabilities: frozenset[str] = frozenset()

    def portable(self) -> dict:
        return {
            "case_id": str(self.case_id),
            "content_digest": digest_content(self.content),
            "environment_revision_id": str(self.environment_revision_id) if self.environment_revision_id else None,
            "observation_mode": self.observation_mode.value,
            "gate_profile": self.gate_profile,
            "provided_capabilities": sorted(self.provided_capabilities),
        }


@dataclass(frozen=True)
class SubmitOutcome:
    run_id: UUID
    snapshot_digest: str
    created: bool
    blocked: bool
    blocked_reasons: tuple[str, ...]
    planned_executions: int
    status: str


@dataclass(frozen=True)
class ControlReceipt:
    control_id: UUID
    control_revision: int


@dataclass(frozen=True)
class CaseRevisionInfo:
    revision_id: UUID
    case_id: UUID
    logical_key: str
    content_digest: str
    required_capabilities: tuple[str, ...]


class RunService:
    def __init__(self, engine: AsyncEngine, *, events: EventService | None = None) -> None:
        self._factory = create_session_factory(engine)
        self._events = events or EventService(engine)

    async def submit(self, request: SubmitRequest) -> SubmitOutcome:
        request_digest = digest_content(request.portable())
        try:
            return await self._submit_transaction(request, request_digest)
        except _ConcurrentReplay:
            return await self._replay(request, operation=SUBMIT_OPERATION)

    async def submit_draft(self, request: DraftSubmitRequest) -> SubmitOutcome:
        validate_content("case", request.content)
        compiled = compile_case_document(yaml.safe_dump(request.content, allow_unicode=True, sort_keys=False))
        capabilities = sorted(compiled.capabilities)
        request_digest = digest_content(request.portable())
        try:
            return await self._submit_draft_transaction(request, request_digest, capabilities)
        except _ConcurrentReplay:
            return await self._replay(request, operation=DRAFT_SUBMIT_OPERATION)

    async def _replay(self, request, *, operation: str = SUBMIT_OPERATION) -> SubmitOutcome:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=request.principal_id, workspace_id=request.workspace_id)
            existing = (
                await session.execute(
                    sa.select(tables.idempotency_keys).where(
                        tables.idempotency_keys.c.workspace_id == request.workspace_id,
                        tables.idempotency_keys.c.principal == str(request.principal_id),
                        tables.idempotency_keys.c.operation == operation,
                        tables.idempotency_keys.c.key == request.idempotency_key,
                    )
                )
            ).one_or_none()
        if existing is None:
            raise IdempotencyConflict()
        stored = json.loads(existing.response_ref or "{}")
        return SubmitOutcome(
            run_id=UUID(stored["run_id"]),
            snapshot_digest=stored["snapshot_digest"],
            created=False,
            blocked=stored["blocked"],
            blocked_reasons=tuple(stored["blocked_reasons"]),
            planned_executions=stored["planned_executions"],
            status=stored["status"],
        )

    async def _submit_transaction(self, request: SubmitRequest, request_digest: str) -> SubmitOutcome:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=request.principal_id, workspace_id=request.workspace_id)
            existing = (
                await session.execute(
                    sa.select(tables.idempotency_keys).where(
                        tables.idempotency_keys.c.workspace_id == request.workspace_id,
                        tables.idempotency_keys.c.principal == str(request.principal_id),
                        tables.idempotency_keys.c.operation == SUBMIT_OPERATION,
                        tables.idempotency_keys.c.key == request.idempotency_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IdempotencyConflict()
                stored = json.loads(existing.response_ref or "{}")
                return SubmitOutcome(
                    run_id=UUID(stored["run_id"]),
                    snapshot_digest=stored["snapshot_digest"],
                    created=False,
                    blocked=stored["blocked"],
                    blocked_reasons=tuple(stored["blocked_reasons"]),
                    planned_executions=stored["planned_executions"],
                    status=stored["status"],
                )

            revisions, facts = await self._resolve_case_revisions(session, request)
            capabilities = sorted({cap for revision in revisions for cap in revision.required_capabilities})
            unsupported = sorted(set(capabilities) - request.provided_capabilities)
            facts.extend(f"capability_unavailable:{cap}" for cap in unsupported)
            if request.environment_revision_id is not None:
                environment = (
                    await session.execute(
                        sa.select(tables.environment_revisions.c.id).where(
                            tables.environment_revisions.c.workspace_id == request.workspace_id,
                            tables.environment_revisions.c.id == request.environment_revision_id,
                            tables.environment_revisions.c.lifecycle == "ready",
                        )
                    )
                ).one_or_none()
                if environment is None:
                    facts.append(f"unknown_environment_revision:{request.environment_revision_id}")

            snapshot = RunSnapshot(
                snapshot_version=1,
                resolved_revision_ids={str(revision.case_id): revision.revision_id for revision in revisions},
                content_digests=[revision.content_digest for revision in revisions],
                environment_revision=request.environment_revision_id,
                policy=request.policy,
                observation_mode=request.observation_mode,
                budgets=dict(request.budgets),
                cache_profile=request.cache_profile,
                gate_profile=request.gate_profile,
            )
            snapshot_content = snapshot.model_dump(mode="json")
            snapshot_digest = digest_run_snapshot(snapshot_content)
            run_id = uuid4()
            blocked = bool(facts)
            await session.execute(
                sa.insert(tables.runs).values(
                    id=run_id,
                    workspace_id=request.workspace_id,
                    status="queued",
                    reasons=facts,
                )
            )
            await session.execute(
                sa.insert(tables.run_snapshots).values(
                    workspace_id=request.workspace_id,
                    run_id=run_id,
                    snapshot_version=1,
                    content=snapshot_content,
                    content_digest=snapshot_digest,
                )
            )
            await session.execute(
                sa.update(tables.runs)
                .where(tables.runs.c.id == run_id)
                .values(snapshot_id=None, updated_at=datetime.now(UTC))
            )
            planned = 0
            if not blocked:
                for revision in revisions:
                    execution_id = uuid4()
                    await session.execute(
                        sa.insert(tables.executions).values(
                            id=execution_id,
                            workspace_id=request.workspace_id,
                            run_id=run_id,
                            case_revision_id=revision.revision_id,
                            logical_key=revision.logical_key,
                            status="queued",
                        )
                    )
                    await session.execute(
                        sa.insert(tables.jobs).values(
                            workspace_id=request.workspace_id,
                            run_id=run_id,
                            execution_id=execution_id,
                            kind="browser_run",
                            state="queued",
                        )
                    )
                    planned += 1
            await self._events.append(
                session,
                workspace_id=request.workspace_id,
                run_id=run_id,
                event_type="run.state_changed",
                actor=request.actor,
                payload={"status": "queued", "blocked": blocked},
            )
            outcome = SubmitOutcome(
                run_id=run_id,
                snapshot_digest=snapshot_digest,
                created=True,
                blocked=blocked,
                blocked_reasons=tuple(facts),
                planned_executions=planned,
                status="queued",
            )
            inserted = (
                await session.execute(
                    pg_insert(tables.idempotency_keys)
                    .values(
                        workspace_id=request.workspace_id,
                        principal=str(request.principal_id),
                        operation=SUBMIT_OPERATION,
                        key=request.idempotency_key,
                        request_digest=request_digest,
                        response_ref=json.dumps(
                            {
                                "run_id": str(outcome.run_id),
                                "snapshot_digest": outcome.snapshot_digest,
                                "blocked": outcome.blocked,
                                "blocked_reasons": list(outcome.blocked_reasons),
                                "planned_executions": outcome.planned_executions,
                                "status": outcome.status,
                            }
                        ),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            tables.idempotency_keys.c.workspace_id,
                            tables.idempotency_keys.c.principal,
                            tables.idempotency_keys.c.operation,
                            tables.idempotency_keys.c.key,
                        ]
                    )
                    .returning(tables.idempotency_keys.c.id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                raise _ConcurrentReplay()
        return outcome

    async def _submit_draft_transaction(
        self, request: DraftSubmitRequest, request_digest: str, capabilities: list[str]
    ) -> SubmitOutcome:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=request.principal_id, workspace_id=request.workspace_id)
            existing = (
                await session.execute(
                    sa.select(tables.idempotency_keys).where(
                        tables.idempotency_keys.c.workspace_id == request.workspace_id,
                        tables.idempotency_keys.c.principal == str(request.principal_id),
                        tables.idempotency_keys.c.operation == DRAFT_SUBMIT_OPERATION,
                        tables.idempotency_keys.c.key == request.idempotency_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IdempotencyConflict()
                stored = json.loads(existing.response_ref or "{}")
                return SubmitOutcome(
                    run_id=UUID(stored["run_id"]),
                    snapshot_digest=stored["snapshot_digest"],
                    created=False,
                    blocked=stored["blocked"],
                    blocked_reasons=tuple(stored["blocked_reasons"]),
                    planned_executions=stored["planned_executions"],
                    status=stored["status"],
                )
            facts: list[str] = []
            unsupported = sorted(set(capabilities) - request.provided_capabilities)
            facts.extend(f"capability_unavailable:{cap}" for cap in unsupported)
            case_row = (
                await session.execute(
                    sa.select(tables.cases.c.logical_key).where(
                        tables.cases.c.workspace_id == request.workspace_id,
                        tables.cases.c.id == request.case_id,
                    )
                )
            ).one_or_none()
            if case_row is None:
                facts.append(f"unknown_case:{request.case_id}")
            if request.environment_revision_id is not None:
                environment = (
                    await session.execute(
                        sa.select(tables.environment_revisions.c.id).where(
                            tables.environment_revisions.c.workspace_id == request.workspace_id,
                            tables.environment_revisions.c.id == request.environment_revision_id,
                            tables.environment_revisions.c.lifecycle == "ready",
                        )
                    )
                ).one_or_none()
                if environment is None:
                    facts.append(f"unknown_environment_revision:{request.environment_revision_id}")
            content_digest = digest_content(request.content)
            snapshot = RunSnapshot(
                snapshot_version=1,
                content_digests=[content_digest],
                environment_revision=request.environment_revision_id,
                policy="replay",
                observation_mode=request.observation_mode,
                gate_profile=request.gate_profile,
                provisional=True,
                draft_case=request.content,
            )
            snapshot_content = snapshot.model_dump(mode="json")
            snapshot_digest = digest_run_snapshot(snapshot_content)
            run_id = uuid4()
            blocked = bool(facts)
            await session.execute(
                sa.insert(tables.runs).values(
                    id=run_id,
                    workspace_id=request.workspace_id,
                    status="queued",
                    reasons=facts,
                )
            )
            await session.execute(
                sa.insert(tables.run_snapshots).values(
                    workspace_id=request.workspace_id,
                    run_id=run_id,
                    snapshot_version=1,
                    content=snapshot_content,
                    content_digest=snapshot_digest,
                )
            )
            planned = 0
            if not blocked:
                execution_id = uuid4()
                await session.execute(
                    sa.insert(tables.executions).values(
                        id=execution_id,
                        workspace_id=request.workspace_id,
                        run_id=run_id,
                        case_revision_id=None,
                        logical_key=case_row.logical_key if case_row is not None else "draft",
                        status="queued",
                    )
                )
                await session.execute(
                    sa.insert(tables.jobs).values(
                        workspace_id=request.workspace_id,
                        run_id=run_id,
                        execution_id=execution_id,
                        kind="browser_run",
                        state="queued",
                    )
                )
                planned = 1
            await self._events.append(
                session,
                workspace_id=request.workspace_id,
                run_id=run_id,
                event_type="run.state_changed",
                actor=request.actor,
                payload={"status": "queued", "blocked": blocked, "provisional": True},
            )
            outcome = SubmitOutcome(
                run_id=run_id,
                snapshot_digest=snapshot_digest,
                created=True,
                blocked=blocked,
                blocked_reasons=tuple(facts),
                planned_executions=planned,
                status="queued",
            )
            inserted = (
                await session.execute(
                    pg_insert(tables.idempotency_keys)
                    .values(
                        workspace_id=request.workspace_id,
                        principal=str(request.principal_id),
                        operation=DRAFT_SUBMIT_OPERATION,
                        key=request.idempotency_key,
                        request_digest=request_digest,
                        response_ref=json.dumps(
                            {
                                "run_id": str(outcome.run_id),
                                "snapshot_digest": outcome.snapshot_digest,
                                "blocked": outcome.blocked,
                                "blocked_reasons": list(outcome.blocked_reasons),
                                "planned_executions": outcome.planned_executions,
                                "status": outcome.status,
                            }
                        ),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            tables.idempotency_keys.c.workspace_id,
                            tables.idempotency_keys.c.principal,
                            tables.idempotency_keys.c.operation,
                            tables.idempotency_keys.c.key,
                        ]
                    )
                    .returning(tables.idempotency_keys.c.id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                raise _ConcurrentReplay()
        return outcome

    async def _resolve_case_revisions(
        self, session, request: SubmitRequest
    ) -> tuple[list[CaseRevisionInfo], list[str]]:
        facts: list[str] = []
        if not request.case_revision_ids:
            return [], ["no_case_revisions"]
        rows = (
            await session.execute(
                sa.select(
                    tables.case_revisions.c.id,
                    tables.case_revisions.c.case_id,
                    tables.case_revisions.c.content,
                    tables.case_revisions.c.content_digest,
                    tables.cases.c.logical_key,
                )
                .join(
                    tables.cases,
                    sa.and_(
                        tables.cases.c.workspace_id == tables.case_revisions.c.workspace_id,
                        tables.cases.c.id == tables.case_revisions.c.case_id,
                    ),
                )
                .where(
                    tables.case_revisions.c.workspace_id == request.workspace_id,
                    tables.case_revisions.c.id.in_(request.case_revision_ids),
                    tables.case_revisions.c.lifecycle == "ready",
                )
            )
        ).all()
        found = {row.id for row in rows}
        facts.extend(
            f"unknown_case_revision:{revision_id}"
            for revision_id in request.case_revision_ids
            if revision_id not in found
        )
        revisions = [
            CaseRevisionInfo(
                revision_id=row.id,
                case_id=row.case_id,
                logical_key=row.logical_key,
                content_digest=row.content_digest,
                required_capabilities=tuple(row.content.get("required_capabilities", [])),
            )
            for row in rows
        ]
        return revisions, facts

    async def request_control(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        run_id: UUID,
        action: ControlAction,
        reason: str | None = None,
        expected_control_revision: int | None = None,
    ) -> ControlReceipt:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            run_row = (
                await session.execute(
                    sa.select(tables.runs.c.id)
                    .where(tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id)
                    .with_for_update()
                )
            ).one_or_none()
            if run_row is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy run trong scope")
            current = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(tables.run_controls)
                    .where(
                        tables.run_controls.c.workspace_id == workspace_id,
                        tables.run_controls.c.run_id == run_id,
                    )
                )
            ).scalar_one()
            if expected_control_revision is not None and expected_control_revision != current:
                raise ControlConflict()
            control_revision = current + 1
            control_id = (
                await session.execute(
                    sa.insert(tables.run_controls)
                    .values(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        action=action.value,
                        requested_by=actor,
                        reason=reason,
                        expected_control_revision=expected_control_revision,
                        control_revision=control_revision,
                    )
                    .returning(tables.run_controls.c.id)
                )
            ).scalar_one()
            await self._events.append(
                session,
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="control.requested",
                actor=actor,
                payload={"action": action.value, "reason": reason},
            )
        return ControlReceipt(control_id=control_id, control_revision=control_revision)
