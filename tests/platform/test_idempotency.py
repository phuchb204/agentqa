from __future__ import annotations

import asyncio
import json

import pytest
import sqlalchemy as sa
from tests.support.platform import service_case_revision, service_workspace, submit_request
from tests.support.postgres import scoped_transaction

from agentqa.contracts.canonical import digest_content
from agentqa.platform.runs.service import IdempotencyConflict, SubmitRequest
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _setup(runtime):
    user_id, username, workspace_id = await service_workspace(runtime)
    receipt = await service_case_revision(runtime, workspace_id=workspace_id, principal_id=user_id, actor=username)
    return user_id, username, workspace_id, receipt


async def _count(runtime, workspace_id, user_id, table) -> int:
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


async def test_same_key_same_body_replays(runtime) -> None:
    user_id, username, workspace_id, receipt = await _setup(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="replay-key",
    )
    first = await runtime.runs.submit(request)
    second = await runtime.runs.submit(request)
    assert first.created is True
    assert second.created is False
    assert second.run_id == first.run_id
    assert second.snapshot_digest == first.snapshot_digest
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1
    assert await _count(runtime, workspace_id, user_id, tables.executions) == 1
    assert await _count(runtime, workspace_id, user_id, tables.jobs) == 1
    assert await _count(runtime, workspace_id, user_id, tables.run_events) == 1


async def test_same_key_different_body_conflicts(runtime) -> None:
    user_id, username, workspace_id, receipt = await _setup(runtime)
    first = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="conflict-key",
    )
    await runtime.runs.submit(first)
    conflicting = SubmitRequest(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        idempotency_key="conflict-key",
        case_revision_ids=(receipt.revision_id,),
        budgets={"steps": 99},
    )
    with pytest.raises(IdempotencyConflict):
        await runtime.runs.submit(conflicting)
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1


async def test_request_digest_is_stored(runtime) -> None:
    user_id, username, workspace_id, receipt = await _setup(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="digest-key",
    )
    outcome = await runtime.runs.submit(request)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        stored = (
            await session.execute(
                sa.select(tables.idempotency_keys.c.request_digest, tables.idempotency_keys.c.response_ref).where(
                    tables.idempotency_keys.c.key == "digest-key"
                )
            )
        ).one()
    assert stored.request_digest == digest_content(request.portable())
    assert json.loads(stored.response_ref)["run_id"] == str(outcome.run_id)


async def test_concurrent_duplicate_creates_single_run(runtime) -> None:
    user_id, username, workspace_id, receipt = await _setup(runtime)
    request = submit_request(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        revision_id=receipt.revision_id,
        idempotency_key="race-key",
    )
    outcomes = await asyncio.gather(runtime.runs.submit(request), runtime.runs.submit(request))
    created = [outcome for outcome in outcomes if outcome.created]
    replayed = [outcome for outcome in outcomes if not outcome.created]
    assert len(created) == 1 and len(replayed) == 1
    assert created[0].run_id == replayed[0].run_id
    assert await _count(runtime, workspace_id, user_id, tables.runs) == 1
    assert await _count(runtime, workspace_id, user_id, tables.idempotency_keys) == 1
    assert await _count(runtime, workspace_id, user_id, tables.executions) == 1
