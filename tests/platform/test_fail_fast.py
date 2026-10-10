from __future__ import annotations

import pytest
import sqlalchemy as sa
from tests.support.platform import (
    case_content,
    service_case_revision,
    service_suite_revision,
    service_workspace,
    suite_content,
    suite_submit_request,
)
from tests.support.postgres import scoped_transaction

from agentqa.contracts.case import CaseContent
from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.coordinator import ExecutionOutcome, ExecutionSpec, RunEventRecorder
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.runs.worker import RunWorker
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER
from agentqa.verify.completion import CompletionOutcome

pytestmark = pytest.mark.asyncio


async def _rows(runtime, workspace_id, principal_id, statement):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(statement)).all()


async def _suite_setup(runtime, *, fail_fast: bool):
    user_id, username, workspace_id = await service_workspace(runtime)
    for logical_key in ("ff_a", "ff_b", "ff_c"):
        await service_case_revision(
            runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key=logical_key
        )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="ff_suite",
        content=suite_content(
            "ff_suite",
            case_refs=[
                {"logical_key": "ff_a", "revision_no": 1},
                {"logical_key": "ff_b", "revision_no": 1},
                {"logical_key": "ff_c", "revision_no": 1},
            ],
            fail_fast=fail_fast,
        ),
    )
    outcome = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key=f"ff-{fail_fast}",
        )
    )
    assert outcome.planned_executions == 3
    return user_id, username, workspace_id, outcome


def _worker(runtime, *, workspace_id, user_id) -> RunWorker:
    return RunWorker(
        queue=JobQueue(
            create_session_factory(runtime.engines[ROLE_WORKER]),
            workspace_id=workspace_id,
            principal_id=user_id,
        ),
        coordinator=None,
        recorder=RunEventRecorder(runtime.engines[ROLE_API]),
        engine=runtime.engines[ROLE_API],
        principal_id=user_id,
        workspace_id=workspace_id,
        worker_id="fail-fast-worker",
    )


def _spec(user_id, workspace_id, run_id, execution_id, logical_key) -> ExecutionSpec:
    return ExecutionSpec(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=run_id,
        execution_id=execution_id,
        attempt_id=execution_id,
        logical_key=logical_key,
        case=CaseContent.model_validate(case_content(logical_key)),
        target_base_url="http://127.0.0.1:8000",
        fixture_ref="taskboard@1",
        namespace=f"ns-{logical_key}",
    )


def _failed_outcome(execution_id) -> ExecutionOutcome:
    return ExecutionOutcome(
        execution_id=execution_id,
        status="failed",
        verdict="failed",
        gate="passed",
        gate_reasons=[],
        reasons=["assertion_failed"],
        capability={},
        steps=[],
        assertion_results=[],
        completion=CompletionOutcome(complete=True, proof_valid=True),
        trace_refs=[],
        unknown_commands=[],
    )


async def test_fail_fast_marks_pending_executions_skipped(runtime) -> None:
    user_id, _username, workspace_id, outcome = await _suite_setup(runtime, fail_fast=True)
    executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(
            tables.executions.c.id,
            tables.executions.c.logical_key,
            tables.executions.c.status,
        )
        .where(tables.executions.c.run_id == outcome.run_id)
        .order_by(tables.executions.c.created_at, tables.executions.c.id),
    )
    assert [row.status for row in executions] == ["queued", "queued", "queued"]
    first = executions[0]
    worker = _worker(runtime, workspace_id=workspace_id, user_id=user_id)
    await worker._finalize(
        _spec(user_id, workspace_id, outcome.run_id, first.id, first.logical_key), _failed_outcome(first.id)
    )

    after = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.id, tables.executions.c.status, tables.executions.c.gate).where(
            tables.executions.c.run_id == outcome.run_id
        ),
    )
    statuses = {row.id: row.status for row in after}
    assert statuses[first.id] == "failed"
    assert sorted(statuses.values()) == ["failed", "skipped", "skipped"]
    gates = {row.id: row.gate for row in after}
    assert gates[first.id] == "passed"

    jobs = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.jobs.c.execution_id, tables.jobs.c.state).where(tables.jobs.c.run_id == outcome.run_id),
    )
    job_states = {row.execution_id: row.state for row in jobs}
    assert job_states[first.id] == "queued"
    assert list(job_states.values()).count("cancelled") == 2

    runs = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.runs.c.status, tables.runs.c.verdict, tables.runs.c.gate, tables.runs.c.finalized_at).where(
            tables.runs.c.id == outcome.run_id
        ),
    )
    assert runs[0].status == "failed"
    assert runs[0].verdict == "failed"
    assert runs[0].gate == "passed"
    assert runs[0].finalized_at is not None

    events = await runtime.events.query_durable(workspace_id=workspace_id, principal_id=user_id, run_id=outcome.run_id)
    skipped = [event for event in events if event["type"] == "execution.skipped"]
    assert len(skipped) == 2
    assert all(event["summary"]["reason"] == "fail_fast" for event in skipped)
    assert any(event["type"] == "run.finalized" for event in events)

    state = await RunReadModel(runtime.engines[ROLE_API]).run_state(
        workspace_id=workspace_id, principal_id=user_id, run_id=outcome.run_id
    )
    assert state is not None
    assert len(state["executions"]) == 3


async def test_fail_fast_disabled_keeps_pending_queued(runtime) -> None:
    user_id, _username, workspace_id, outcome = await _suite_setup(runtime, fail_fast=False)
    executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.id, tables.executions.c.logical_key)
        .where(tables.executions.c.run_id == outcome.run_id)
        .order_by(tables.executions.c.created_at, tables.executions.c.id),
    )
    first = executions[0]
    worker = _worker(runtime, workspace_id=workspace_id, user_id=user_id)
    await worker._finalize(
        _spec(user_id, workspace_id, outcome.run_id, first.id, first.logical_key), _failed_outcome(first.id)
    )
    after = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.status).where(tables.executions.c.run_id == outcome.run_id),
    )
    statuses = sorted(row.status for row in after)
    assert statuses == ["failed", "queued", "queued"]
    runs = await _rows(
        runtime, workspace_id, user_id, sa.select(tables.runs.c.status).where(tables.runs.c.id == outcome.run_id)
    )
    assert runs[0].status == "queued"


async def test_success_does_not_skip_pending(runtime) -> None:
    user_id, _username, workspace_id, outcome = await _suite_setup(runtime, fail_fast=True)
    executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.id, tables.executions.c.logical_key)
        .where(tables.executions.c.run_id == outcome.run_id)
        .order_by(tables.executions.c.created_at, tables.executions.c.id),
    )
    first = executions[0]
    worker = _worker(runtime, workspace_id=workspace_id, user_id=user_id)
    succeeded = ExecutionOutcome(
        execution_id=first.id,
        status="succeeded",
        verdict="passed",
        gate="passed",
        gate_reasons=[],
        reasons=[],
        capability={},
        steps=[],
        assertion_results=[],
        completion=CompletionOutcome(complete=True, proof_valid=True),
        trace_refs=[],
        unknown_commands=[],
    )
    await worker._finalize(_spec(user_id, workspace_id, outcome.run_id, first.id, first.logical_key), succeeded)
    after = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.status).where(tables.executions.c.run_id == outcome.run_id),
    )
    assert sorted(row.status for row in after) == ["queued", "queued", "succeeded"]
