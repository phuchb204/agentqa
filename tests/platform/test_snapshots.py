from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.support.platform import service_case_revision, service_workspace, submit_request
from tests.support.postgres import scoped_transaction

from agentqa.contracts.runs import ControlAction
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _workspace_with_revision(runtime):
    user_id, username, workspace_id = await service_workspace(runtime)
    receipt = await service_case_revision(runtime, workspace_id=workspace_id, principal_id=user_id, actor=username)
    return user_id, username, workspace_id, receipt


async def test_submit_creates_snapshot_executions_jobs_and_event(runtime) -> None:
    user_id, username, workspace_id, receipt = await _workspace_with_revision(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="submit-1",
    )
    outcome = await runtime.runs.submit(request)
    assert outcome.created is True
    assert outcome.blocked is False
    assert outcome.planned_executions == 1
    assert len(outcome.snapshot_digest) == 64

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        run = (await session.execute(sa.select(tables.runs).where(tables.runs.c.id == outcome.run_id))).one()
        snapshot = (
            await session.execute(
                sa.select(tables.run_snapshots).where(tables.run_snapshots.c.run_id == outcome.run_id)
            )
        ).one()
        executions = (
            await session.execute(sa.select(tables.executions).where(tables.executions.c.run_id == outcome.run_id))
        ).all()
        jobs = (await session.execute(sa.select(tables.jobs).where(tables.jobs.c.run_id == outcome.run_id))).all()
        events = (
            await session.execute(
                sa.select(tables.run_events)
                .where(tables.run_events.c.run_id == outcome.run_id)
                .order_by(tables.run_events.c.run_seq)
            )
        ).all()

    assert run.status == "queued"
    assert run.reasons == []
    assert snapshot.content_digest == outcome.snapshot_digest
    assert snapshot.content["policy"] == "default"
    assert snapshot.content["content_digests"] == [receipt.content_digest]
    assert snapshot.snapshot_version == 1
    assert len(executions) == 1
    assert executions[0].case_revision_id == receipt.revision_id
    assert len(jobs) == 1 and jobs[0].execution_id == executions[0].id
    assert len(events) == 1
    assert events[0].type == "run.state_changed"
    assert events[0].run_seq == 1


async def test_submit_unknown_revision_is_blocked_with_facts(runtime) -> None:
    user_id, username, workspace_id, _receipt = await _workspace_with_revision(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=uuid4(),
        idempotency_key="submit-blocked",
    )
    outcome = await runtime.runs.submit(request)
    assert outcome.blocked is True
    assert any(fact.startswith("unknown_case_revision:") for fact in outcome.blocked_reasons)
    assert outcome.planned_executions == 0

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        executions = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.executions)
                .where(tables.executions.c.run_id == outcome.run_id)
            )
        ).scalar_one()
        run = (await session.execute(sa.select(tables.runs).where(tables.runs.c.id == outcome.run_id))).one()
        events = (
            await session.execute(
                sa.select(tables.run_events.c.summary).where(tables.run_events.c.run_id == outcome.run_id)
            )
        ).all()
    assert executions == 0
    assert run.reasons and run.reasons[0].startswith("unknown_case_revision:")
    assert events[0].summary["blocked"] is True


async def test_environment_and_capability_facts_preserved(runtime) -> None:
    user_id, username, workspace_id, receipt = await _workspace_with_revision(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="submit-env",
        environment_revision_id=uuid4(),
    )
    outcome = await runtime.runs.submit(request)
    assert outcome.blocked is True
    assert any(fact.startswith("unknown_environment_revision:") for fact in outcome.blocked_reasons)


async def test_run_snapshot_is_immutable_config(runtime) -> None:
    user_id, username, workspace_id, receipt = await _workspace_with_revision(runtime)
    first = await runtime.runs.submit(
        submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            revision_id=receipt.revision_id,
            idempotency_key="submit-immutable-1",
        )
    )
    second = await runtime.runs.submit(
        submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            revision_id=receipt.revision_id,
            idempotency_key="submit-immutable-2",
        )
    )
    assert first.run_id != second.run_id
    assert first.snapshot_digest == second.snapshot_digest

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        snapshot = (
            await session.execute(sa.select(tables.run_snapshots).where(tables.run_snapshots.c.run_id == first.run_id))
        ).one()
        revisions = (
            await session.execute(
                sa.select(tables.case_revisions).where(tables.case_revisions.c.id == receipt.revision_id)
            )
        ).one()
    assert snapshot.content_digest == first.snapshot_digest
    assert revisions.content_digest == receipt.content_digest
    assert snapshot.content["resolved_revision_ids"] == {str(revisions.case_id): str(receipt.revision_id)}


async def test_control_requests_are_revisioned(runtime) -> None:
    user_id, username, workspace_id, receipt = await _workspace_with_revision(runtime)
    outcome = await runtime.runs.submit(
        submit_request(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            revision_id=receipt.revision_id,
            idempotency_key="submit-control",
        )
    )
    first = await runtime.runs.request_control(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        run_id=outcome.run_id,
        action=ControlAction.PAUSE,
        reason="maintenance",
        expected_control_revision=0,
    )
    assert first.control_revision == 1
    second = await runtime.runs.request_control(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        run_id=outcome.run_id,
        action=ControlAction.RESUME,
        expected_control_revision=1,
    )
    assert second.control_revision == 2
    from agentqa.platform.runs.service import ControlConflict

    with pytest.raises(ControlConflict):
        await runtime.runs.request_control(
            workspace_id=workspace_id,
            principal_id=user_id,
            actor=username,
            run_id=outcome.run_id,
            action=ControlAction.CANCEL,
            expected_control_revision=1,
        )

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        controls = (
            await session.execute(sa.select(tables.run_controls).where(tables.run_controls.c.run_id == outcome.run_id))
        ).all()
        events = (
            await session.execute(
                sa.select(tables.run_events.c.type)
                .where(tables.run_events.c.run_id == outcome.run_id)
                .order_by(tables.run_events.c.run_seq)
            )
        ).all()
    assert len(controls) == 2
    assert [event.type for event in events] == ["run.state_changed", "control.requested", "control.requested"]
