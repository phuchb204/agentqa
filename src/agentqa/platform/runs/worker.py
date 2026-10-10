from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.case import CaseContent
from agentqa.contracts.runs import TERMINAL_STATUSES, ExecutionStatus, Verdict
from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.coordinator import ExecutionOutcome, ExecutionSpec
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

TERMINAL_VALUES = {item.value for item in TERMINAL_STATUSES}


class ExecutionLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerSummary:
    execution_id: UUID
    status: str
    verdict: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": str(self.execution_id),
            "status": self.status,
            "verdict": self.verdict,
        }


class RunWorker:
    def __init__(
        self,
        *,
        queue: JobQueue,
        coordinator: Any,
        recorder: Any,
        engine: AsyncEngine,
        principal_id: UUID,
        workspace_id: UUID,
        worker_id: str = "worker-1",
    ) -> None:
        self.queue = queue
        self.coordinator = coordinator
        self.recorder = recorder
        self.principal_id = principal_id
        self.workspace_id = workspace_id
        self.worker_id = worker_id
        self._factory = create_session_factory(engine)

    async def run_once(self) -> WorkerSummary | None:
        claim = await self.queue.claim(self.worker_id)
        if claim is None:
            return None
        if claim.execution_id is None:
            await self.queue.quarantine(claim.lease_id, reason="job_without_execution")
            return WorkerSummary(execution_id=UUID(int=0), status="error", verdict=None)
        try:
            spec = await self._load(claim.execution_id)
            pending_control = await self._pending_control(spec.workspace_id, spec.run_id)
            if pending_control is not None:
                await self.coordinator.apply_control(pending_control)
            outcome = await self.coordinator.execute(spec)
            await self._finalize(spec, outcome)
            await self.queue.release(
                claim.lease_id,
                job_state="succeeded" if outcome.status == ExecutionStatus.SUCCEEDED.value else "failed",
            )
            return WorkerSummary(execution_id=spec.execution_id, status=outcome.status, verdict=outcome.verdict)
        except Exception:
            await self.queue.quarantine(claim.lease_id, reason="worker_error")
            raise

    async def run_until_idle(self, *, max_jobs: int = 10) -> list[WorkerSummary]:
        summaries: list[WorkerSummary] = []
        for _ in range(max_jobs):
            summary = await self.run_once()
            if summary is None:
                break
            summaries.append(summary)
        return summaries

    async def _load(self, execution_id: UUID) -> ExecutionSpec:
        async with self._factory() as session, session.begin():
            await set_scope(
                session,
                principal_id=self.principal_id,
                workspace_id=self.workspace_id,
            )
            execution = (
                await session.execute(sa.select(tables.executions).where(tables.executions.c.id == execution_id))
            ).one()
            snapshot = (
                await session.execute(
                    sa.select(tables.run_snapshots).where(tables.run_snapshots.c.run_id == execution.run_id)
                )
            ).one()
            revision = None
            if execution.case_revision_id is not None:
                revision = (
                    await session.execute(
                        sa.select(tables.case_revisions).where(tables.case_revisions.c.id == execution.case_revision_id)
                    )
                ).one()
            environment_content: dict[str, Any] = {}
            environment_id = snapshot.content.get("environment_revision")
            if environment_id:
                environment = (
                    await session.execute(
                        sa.select(tables.environment_revisions).where(
                            tables.environment_revisions.c.id == UUID(str(environment_id))
                        )
                    )
                ).one_or_none()
                if environment is None:
                    raise ExecutionLoadError("environment revision không tồn tại")
                environment_content = dict(environment.content or {})
            attempt = (
                await session.execute(
                    sa.select(tables.attempts)
                    .where(tables.attempts.c.execution_id == execution_id)
                    .order_by(tables.attempts.c.attempt_no.desc())
                    .limit(1)
                )
            ).one_or_none()
        for key in ("target_base_url", "fixture_ref", "namespace"):
            if not environment_content.get(key):
                raise ExecutionLoadError(f"environment thiếu '{key}'")
        if revision is not None:
            case = CaseContent.model_validate(revision.content)
        else:
            draft_case = snapshot.content.get("draft_case")
            if not draft_case:
                raise ExecutionLoadError("draft case không tồn tại trong snapshot")
            case = CaseContent.model_validate(draft_case)
        return ExecutionSpec(
            workspace_id=execution.workspace_id,
            principal_id=self.principal_id,
            run_id=execution.run_id,
            execution_id=execution.id,
            attempt_id=attempt.id if attempt is not None else execution.id,
            logical_key=execution.logical_key,
            case=case,
            target_base_url=str(environment_content["target_base_url"]),
            fixture_ref=str(environment_content["fixture_ref"]),
            namespace=str(environment_content["namespace"]),
            parameters=dict(environment_content.get("parameters", {})),
            gate_profile=str(snapshot.content.get("gate_profile", "strict")),
            fence_epoch=int(attempt.fence_epoch) if attempt is not None else 1,
            policy=str(snapshot.content.get("policy", "replay")),
            observation_mode=str(snapshot.content.get("observation_mode", "semantic")),
            snapshot_digest=str(snapshot.content_digest or ""),
            provisional=bool(snapshot.content.get("provisional")),
            case_id=revision.case_id if revision is not None else None,
            case_revision_id=execution.case_revision_id,
        )

    async def _pending_control(self, workspace_id: UUID, run_id: UUID) -> UUID | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=self.principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.run_controls.c.id)
                    .where(
                        tables.run_controls.c.workspace_id == workspace_id,
                        tables.run_controls.c.run_id == run_id,
                        tables.run_controls.c.effective_at.is_(None),
                    )
                    .order_by(tables.run_controls.c.requested_at.desc(), tables.run_controls.c.id.desc())
                    .limit(1)
                )
            ).one_or_none()
        return row.id if row is not None else None

    async def _finalize(self, spec: ExecutionSpec, outcome: ExecutionOutcome) -> None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=spec.principal_id, workspace_id=spec.workspace_id)
            await session.execute(
                sa.update(tables.executions)
                .where(tables.executions.c.id == spec.execution_id)
                .values(status=outcome.status, verdict=outcome.verdict, updated_at=datetime.now(UTC))
            )
            for result in outcome.assertion_results:
                await session.execute(
                    sa.insert(tables.assertion_results).values(
                        workspace_id=spec.workspace_id,
                        run_id=spec.run_id,
                        execution_id=spec.execution_id,
                        checkpoint_id=result.step_id,
                        assertion_id=result.assertion_id,
                        result=result.status.value,
                        proof_ref=json.dumps(
                            {
                                "expected": result.expected_redacted,
                                "observed": result.observed_redacted,
                                "evidence": result.evidence_status.value,
                                "applicable": result.applicable,
                                "reason": result.reason,
                                "trace_refs": list(outcome.trace_refs),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            for record in outcome.healing_records:
                await session.execute(
                    sa.insert(tables.healing_records).values(
                        workspace_id=spec.workspace_id,
                        run_id=spec.run_id,
                        execution_id=spec.execution_id,
                        attempt_id=spec.attempt_id,
                        actor=record.actor.value,
                        node_id=record.node_id,
                        opportunity_id=record.opportunity_id,
                        attempt_ref=record.attempt_id,
                        decision=record.decision.value,
                        ranking=record.ranking.model_dump(mode="json") if record.ranking is not None else None,
                        expected_signature=record.expected_signature,
                        actual_signature=record.actual_signature,
                        original_target=(
                            record.original_target.model_dump(mode="json")
                            if record.original_target is not None
                            else None
                        ),
                        actual_target=(
                            record.actual_target.model_dump(mode="json") if record.actual_target is not None else None
                        ),
                        dispatch_outcome=record.dispatch_outcome,
                        guard_checks=list(record.guard_checks),
                        postconditions_ok=record.postconditions_ok,
                        refusal_reason=record.refusal_reason,
                        error=record.error,
                        proposal=record.proposal.model_dump(mode="json") if record.proposal is not None else None,
                        source_run_id=(
                            record.proposal.source_run_id
                            if record.proposal is not None and record.proposal.source_run_id is not None
                            else spec.run_id
                        ),
                        case_id=spec.case_id,
                        case_revision_id=spec.case_revision_id,
                        recorded_at=record.recorded_at,
                    )
                )
            rows = (
                await session.execute(
                    sa.select(tables.executions.c.status, tables.executions.c.verdict).where(
                        tables.executions.c.run_id == spec.run_id
                    )
                )
            ).all()
            statuses = [row.status for row in rows]
            verdicts = [row.verdict for row in rows]
            if all(status in TERMINAL_VALUES for status in statuses):
                await session.execute(
                    sa.update(tables.runs)
                    .where(tables.runs.c.id == spec.run_id)
                    .values(
                        status=_compose_run_status(statuses, verdicts),
                        verdict=_compose_run_verdict(verdicts),
                        gate=outcome.gate if len(rows) == 1 else None,
                        reasons=outcome.reasons,
                        finalized_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
        await self.recorder.record(
            workspace_id=spec.workspace_id,
            principal_id=spec.principal_id,
            run_id=spec.run_id,
            execution_id=spec.execution_id,
            event_type="run.finalized",
            actor=spec.actor,
            payload={"status": outcome.status, "verdict": outcome.verdict, "execution_id": str(spec.execution_id)},
        )


def _compose_run_status(statuses: list[str], verdicts: list[str | None]) -> str:
    if any(verdict == Verdict.FAILED.value for verdict in verdicts):
        return ExecutionStatus.FAILED.value
    if all(status == ExecutionStatus.SUCCEEDED.value for status in statuses):
        return ExecutionStatus.SUCCEEDED.value
    if any(status == ExecutionStatus.CANCELLED.value for status in statuses):
        return ExecutionStatus.CANCELLED.value
    return ExecutionStatus.INCONCLUSIVE.value


def _compose_run_verdict(verdicts: list[str | None]) -> str:
    if any(verdict == Verdict.FAILED.value for verdict in verdicts):
        return Verdict.FAILED.value
    if all(verdict == Verdict.PASSED.value for verdict in verdicts):
        return Verdict.PASSED.value
    return Verdict.INCONCLUSIVE.value
