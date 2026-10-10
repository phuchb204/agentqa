from __future__ import annotations

import pytest
import sqlalchemy as sa
from tests.support.platform import (
    dataset_content,
    service_case_revision,
    service_dataset_revision,
    service_suite_revision,
    service_workspace,
    suite_content,
    suite_submit_request,
)
from tests.support.postgres import scoped_transaction

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _rows(runtime, workspace_id, principal_id, statement):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(statement)).all()


async def _events(runtime, workspace_id, principal_id, run_id):
    return await runtime.events.query_durable(workspace_id=workspace_id, principal_id=principal_id, run_id=run_id)


async def _matrix_setup(runtime):
    user_id, username, workspace_id = await service_workspace(runtime)
    case_a = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="case_a"
    )
    case_b = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="case_b"
    )
    dataset = await service_dataset_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="rows",
        rows=[{"item": "alpha"}, {"item": "beta"}],
    )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="matrix_suite",
        content=suite_content(
            "matrix_suite",
            case_refs=[
                {"logical_key": "case_a", "revision_no": case_a.revision_no},
                {"logical_key": "case_b", "revision_no": case_b.revision_no},
            ],
            fixture_refs=["taskboard@1"],
            dataset_ref="rows",
            dataset_revision_no=dataset.revision_no,
        ),
    )
    return user_id, username, workspace_id, case_a, case_b, dataset, suite


async def test_suite_submit_materializes_full_matrix(runtime) -> None:
    user_id, username, workspace_id, case_a, case_b, dataset, suite = await _matrix_setup(runtime)
    outcome = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key="matrix-1",
        )
    )
    assert outcome.created is True
    assert outcome.blocked is False
    assert outcome.planned_executions == 4

    executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(
            tables.executions.c.id,
            tables.executions.c.logical_key,
            tables.executions.c.execution_key,
            tables.executions.c.dataset_row_index,
            tables.executions.c.parameters,
            tables.executions.c.case_revision_id,
            tables.executions.c.status,
        ).where(tables.executions.c.run_id == outcome.run_id),
    )
    assert len(executions) == 4
    keys = {row.execution_key for row in executions}
    assert keys == {
        f"{suite.revision_id}:case_a:{case_a.revision_no}:row0",
        f"{suite.revision_id}:case_a:{case_a.revision_no}:row1",
        f"{suite.revision_id}:case_b:{case_b.revision_no}:row0",
        f"{suite.revision_id}:case_b:{case_b.revision_no}:row1",
    }
    for row in executions:
        assert row.status == "queued"
        assert row.parameters in ({"item": "alpha"}, {"item": "beta"})
        assert row.dataset_row_index in (0, 1)
        expected_revision = case_a.revision_id if row.logical_key == "case_a" else case_b.revision_id
        assert row.case_revision_id == expected_revision

    jobs = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.jobs.c.execution_id, tables.jobs.c.state, tables.jobs.c.payload).where(
            tables.jobs.c.run_id == outcome.run_id
        ),
    )
    assert len(jobs) == 4
    assert all(job.state == "queued" for job in jobs)
    execution_ids = {row.id for row in executions}
    assert {job.execution_id for job in jobs} == execution_ids
    for job in jobs:
        assert job.payload["fail_fast"] is False
        scopes = {entry["scope"] for entry in job.payload["resource_keys"]}
        assert {"workspace", "browser"} <= scopes

    snapshots = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.run_snapshots.c.content).where(tables.run_snapshots.c.run_id == outcome.run_id),
    )
    content = snapshots[0].content
    assert content["suite_revision"] == str(suite.revision_id)
    assert content["dataset_revision"] == str(dataset.revision_id)
    assert content["fixture_refs"] == ["taskboard@1"]
    assert str(case_a.revision_id) in [str(value) for value in content["resolved_revision_ids"].values()]

    events = await _events(runtime, workspace_id, user_id, outcome.run_id)
    materialized = [event for event in events if event["type"] == "suite.materialized"]
    assert len(materialized) == 1
    assert set(materialized[0]["summary"]["execution_keys"]) == keys
    assert materialized[0]["summary"]["planned_executions"] == 4


async def test_suite_submit_idempotent_replay(runtime) -> None:
    user_id, username, workspace_id, _case_a, _case_b, _dataset, suite = await _matrix_setup(runtime)
    request = suite_submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        suite_revision_id=suite.revision_id,
        idempotency_key="matrix-replay",
    )
    first = await runtime.runs.submit(request)
    second = await runtime.runs.submit(request)
    assert first.created is True
    assert second.created is False
    assert second.run_id == first.run_id
    runs = await _rows(runtime, workspace_id, user_id, sa.select(sa.func.count()).select_from(tables.runs))
    assert runs[0][0] == 1
    executions = await _rows(runtime, workspace_id, user_id, sa.select(sa.func.count()).select_from(tables.executions))
    assert executions[0][0] == 4


async def test_suite_missing_case_refs_blocks_without_executions(runtime) -> None:
    user_id, username, workspace_id = await service_workspace(runtime)
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="broken_suite",
        content=suite_content("broken_suite", case_refs=[{"logical_key": "ghost", "revision_no": 1}]),
    )
    outcome = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key="broken-1",
        )
    )
    assert outcome.blocked is True
    assert outcome.planned_executions == 0
    assert "missing_case:ghost" in outcome.blocked_reasons
    executions = await _rows(runtime, workspace_id, user_id, sa.select(sa.func.count()).select_from(tables.executions))
    jobs = await _rows(runtime, workspace_id, user_id, sa.select(sa.func.count()).select_from(tables.jobs))
    assert executions[0][0] == 0
    assert jobs[0][0] == 0


async def test_suite_pins_dataset_revision(runtime) -> None:
    user_id, username, workspace_id = await service_workspace(runtime)
    case = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="pinned_case"
    )
    dataset_entity = await runtime.revisions.create_entity(
        workspace_id=workspace_id, principal_id=user_id, kind="dataset", logical_key="pin_rows"
    )
    first_dataset = await runtime.revisions.promote_content(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        kind="dataset",
        entity_id=dataset_entity.id,
        content=dataset_content("pin_rows", [{"item": "one"}]),
    )
    await runtime.revisions.promote_content(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        kind="dataset",
        entity_id=dataset_entity.id,
        content=dataset_content("pin_rows", [{"item": "one"}, {"item": "two"}, {"item": "three"}]),
    )
    suite = await service_suite_revision(
        runtime,
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        logical_key="pinned_suite",
        content=suite_content(
            "pinned_suite",
            case_refs=[{"logical_key": "pinned_case", "revision_no": case.revision_no}],
            dataset_ref="pin_rows",
            dataset_revision_no=first_dataset.revision_no,
        ),
    )
    outcome = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key="pin-1",
        )
    )
    assert outcome.planned_executions == 1
    snapshots = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.run_snapshots.c.content).where(tables.run_snapshots.c.run_id == outcome.run_id),
    )
    assert snapshots[0].content["dataset_revision"] == str(first_dataset.revision_id)


async def test_suite_rerun_creates_new_run_without_overwriting(runtime) -> None:
    user_id, username, workspace_id, _case_a, _case_b, _dataset, suite = await _matrix_setup(runtime)
    first = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key="rerun-1",
        )
    )
    first_executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.id, tables.executions.c.execution_key).where(
            tables.executions.c.run_id == first.run_id
        ),
    )
    second = await runtime.runs.submit(
        suite_submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            suite_revision_id=suite.revision_id,
            idempotency_key="rerun-2",
        )
    )
    assert second.run_id != first.run_id
    assert second.planned_executions == 4
    first_after = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(tables.executions.c.id, tables.executions.c.execution_key).where(
            tables.executions.c.run_id == first.run_id
        ),
    )
    assert sorted(first_after, key=lambda row: str(row.id)) == sorted(first_executions, key=lambda row: str(row.id))
    second_executions = await _rows(
        runtime,
        workspace_id,
        user_id,
        sa.select(sa.func.count()).select_from(tables.executions).where(tables.executions.c.run_id == second.run_id),
    )
    assert second_executions[0][0] == 4
