from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.evaluation.effects import RefResolver
from agentqa.platform.evaluation.models import (
    EVALUATOR_VERSION,
    SCHEMA_VERSION,
    EvaluationInput,
    HealingAttempt,
    OracleRecord,
)
from agentqa.platform.evaluation.scoring import score, target_identity
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

SAFE_RESULT_FIELDS = (
    "id",
    "run_id",
    "revision_no",
    "evaluator_version",
    "schema_version",
    "input_digest",
    "oracle_digest",
    "oracle_task_outcome",
    "scorable",
    "unscorable_reason",
    "product_verdict",
    "product_gate",
    "false_pass",
    "labels",
    "counters",
    "superseded_by",
    "recorded_at",
)


class EvaluationService:
    def __init__(self, engine: AsyncEngine, *, ref_resolver: RefResolver | None = None) -> None:
        self._factory = create_session_factory(engine)
        self._ref_resolver = ref_resolver

    async def _collect_input(self, session, *, workspace_id: UUID, run_id: UUID, scheduled: bool) -> EvaluationInput:
        run = (
            await session.execute(
                sa.select(tables.runs.c.status, tables.runs.c.verdict, tables.runs.c.gate).where(
                    tables.runs.c.workspace_id == workspace_id, tables.runs.c.id == run_id
                )
            )
        ).one_or_none()
        if run is None:
            raise KeyError(f"run {run_id} không tồn tại trong scope")
        snapshot_digest = (
            await session.execute(
                sa.select(tables.run_snapshots.c.content_digest).where(
                    tables.run_snapshots.c.workspace_id == workspace_id,
                    tables.run_snapshots.c.run_id == run_id,
                )
            )
        ).scalar_one_or_none() or ""
        executions = (
            await session.execute(
                sa.select(
                    tables.executions.c.id,
                    tables.executions.c.status,
                    tables.executions.c.parameters,
                )
                .where(tables.executions.c.workspace_id == workspace_id, tables.executions.c.run_id == run_id)
                .order_by(tables.executions.c.created_at, tables.executions.c.id)
            )
        ).all()
        assertion_rows = (
            await session.execute(
                sa.select(tables.assertion_results.c.assertion_id, tables.assertion_results.c.result).where(
                    tables.assertion_results.c.workspace_id == workspace_id,
                    tables.assertion_results.c.run_id == run_id,
                )
            )
        ).all()
        healing_rows = (
            await session.execute(
                sa.select(
                    tables.healing_records.c.opportunity_id,
                    tables.healing_records.c.attempt_ref,
                    tables.healing_records.c.decision,
                    tables.healing_records.c.actual_target,
                    tables.healing_records.c.guard_checks,
                    tables.healing_records.c.postconditions_ok,
                    tables.healing_records.c.dispatch_outcome,
                    tables.healing_records.c.error,
                )
                .where(
                    tables.healing_records.c.workspace_id == workspace_id,
                    tables.healing_records.c.run_id == run_id,
                )
                .order_by(tables.healing_records.c.recorded_at, tables.healing_records.c.id)
            )
        ).all()
        probe_event = (
            await session.execute(
                sa.select(tables.run_events.c.summary)
                .where(
                    tables.run_events.c.workspace_id == workspace_id,
                    tables.run_events.c.run_id == run_id,
                    tables.run_events.c.type == "fixture.probed",
                )
                .order_by(tables.run_events.c.run_seq.desc())
                .limit(1)
            )
        ).one_or_none()
        probe = None
        namespace = ""
        if probe_event is not None and isinstance(probe_event.summary, dict):
            probe = probe_event.summary.get("probe")
            namespace = str(probe_event.summary.get("namespace", ""))
        parameters: dict[str, Any] = {}
        for execution in executions:
            if isinstance(execution.parameters, dict):
                parameters = dict(execution.parameters)
                break

        attempts = [
            HealingAttempt(
                opportunity_id=row.opportunity_id,
                attempt_ref=row.attempt_ref,
                decision=row.decision,
                actual_identity=target_identity(row.actual_target),
                guard_checks=list(row.guard_checks or []),
                postconditions_ok=row.postconditions_ok,
                dispatch_outcome=row.dispatch_outcome,
                error=row.error,
            )
            for row in healing_rows
        ]
        return EvaluationInput(
            run_id=str(run_id),
            execution_status=str(run.status),
            product_verdict=run.verdict,
            product_gate=run.gate,
            snapshot_digest=snapshot_digest,
            scheduled=scheduled,
            namespace=namespace,
            parameters=parameters,
            probe=probe,
            probe_missing=probe is None,
            healing_attempts=attempts,
            assertion_statuses={row.assertion_id: row.result for row in assertion_rows},
        )

    async def evaluate_run(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_id: UUID,
        oracle: OracleRecord,
        scheduled: bool = True,
    ) -> dict[str, Any]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            evaluation_input = await self._collect_input(
                session, workspace_id=workspace_id, run_id=run_id, scheduled=scheduled
            )
            if evaluation_input.probe is not None and self._ref_resolver is not None and evaluation_input.namespace:
                ref = evaluation_input.probe.get("last_write_ref")
                if not isinstance(ref, str):
                    last_target = evaluation_input.probe.get("last_write_target")
                    if isinstance(last_target, dict):
                        ref = last_target.get("entity_id")
                if isinstance(ref, str):
                    evaluation_input.actual_target_entity = self._ref_resolver(
                        oracle.app, evaluation_input.namespace, ref
                    )
            result = score(evaluation_input, oracle, ref_resolver=self._ref_resolver)
            previous = (
                await session.execute(
                    sa.select(tables.evaluation_results.c.id, tables.evaluation_results.c.revision_no)
                    .where(
                        tables.evaluation_results.c.workspace_id == workspace_id,
                        tables.evaluation_results.c.run_id == run_id,
                    )
                    .order_by(tables.evaluation_results.c.revision_no.desc())
                    .limit(1)
                )
            ).one_or_none()
            revision_no = (previous.revision_no + 1) if previous is not None else 1
            execution_id = (
                await session.execute(
                    sa.select(tables.executions.c.id)
                    .where(
                        tables.executions.c.workspace_id == workspace_id,
                        tables.executions.c.run_id == run_id,
                    )
                    .order_by(tables.executions.c.created_at, tables.executions.c.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            row_id = (
                await session.execute(
                    sa.insert(tables.evaluation_results)
                    .values(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        execution_id=execution_id,
                        revision_no=revision_no,
                        evaluator_version=EVALUATOR_VERSION,
                        schema_version=SCHEMA_VERSION,
                        input_digest=result.input_digest,
                        oracle_digest=result.oracle_digest,
                        oracle_task_outcome=result.task_outcome.value,
                        scorable=result.scorable,
                        unscorable_reason=result.unscorable_reason,
                        product_verdict=result.product_verdict,
                        product_gate=result.product_gate,
                        false_pass=result.false_pass,
                        labels=[label.model_dump(mode="json") for label in result.labels],
                        counters=result.counters,
                        recorded_at=datetime.now(UTC),
                    )
                    .returning(tables.evaluation_results.c.id)
                )
            ).scalar_one()
            if previous is not None:
                await session.execute(
                    sa.update(tables.evaluation_results)
                    .where(tables.evaluation_results.c.id == previous.id)
                    .values(superseded_by=row_id)
                )
            stored = (
                await session.execute(
                    sa.select(tables.evaluation_results).where(tables.evaluation_results.c.id == row_id)
                )
            ).one()
        return self._view(stored)

    async def list_results(self, *, workspace_id: UUID, principal_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.evaluation_results)
                    .where(
                        tables.evaluation_results.c.workspace_id == workspace_id,
                        tables.evaluation_results.c.run_id == run_id,
                    )
                    .order_by(tables.evaluation_results.c.revision_no)
                )
            ).all()
        return [self._view(row) for row in rows]

    def _view(self, row) -> dict[str, Any]:
        view = {field: getattr(row, field) for field in SAFE_RESULT_FIELDS}
        if isinstance(view.get("recorded_at"), datetime):
            view["recorded_at"] = view["recorded_at"].isoformat()
        return view
