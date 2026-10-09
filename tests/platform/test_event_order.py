from __future__ import annotations

import asyncio

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction

from agentqa.platform.events.service import NOTIFY_CHANNEL
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API
from agentqa.platform.storage.scope import set_scope

pytestmark = pytest.mark.asyncio


async def _setup_run_with_executions(runtime):
    user_id, username, workspace_id = await service_workspace(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        run_id = (
            await session.execute(
                sa.insert(tables.runs).values(workspace_id=workspace_id, status="running").returning(tables.runs.c.id)
            )
        ).scalar_one()
        execution_ids = []
        for key in ("case-a", "case-b"):
            execution_ids.append(
                (
                    await session.execute(
                        sa.insert(tables.executions)
                        .values(workspace_id=workspace_id, run_id=run_id, logical_key=key)
                        .returning(tables.executions.c.id)
                    )
                ).scalar_one()
            )
    return user_id, username, workspace_id, run_id, execution_ids


async def test_sequences_and_payloads_in_one_transaction(runtime) -> None:
    user_id, username, workspace_id, run_id, (execution_a, execution_b) = await _setup_run_with_executions(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        first = await runtime.events.append(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="action.prepared",
            actor=username,
            execution_id=execution_a,
            payload={"i": 1},
            payload_doc={"heavy": "payload-1"},
        )
        second = await runtime.events.append(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="action.prepared",
            actor=username,
            execution_id=execution_a,
            payload={"i": 2},
        )
        third = await runtime.events.append(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="action.prepared",
            actor=username,
            execution_id=execution_b,
            payload={"i": 3},
            payload_doc={"heavy": "payload-2"},
        )
    assert (first.run_seq, second.run_seq, third.run_seq) == (1, 2, 3)
    assert (first.execution_seq, second.execution_seq) == (1, 2)
    assert third.execution_seq == 1

    durable = await runtime.events.query_durable(workspace_id=workspace_id, principal_id=user_id, run_id=run_id)
    assert [row["run_seq"] for row in durable] == [1, 2, 3]
    after_first = await runtime.events.query_durable(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, after_run_seq=1
    )
    assert [row["run_seq"] for row in after_first] == [2, 3]

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        payloads = (
            await session.execute(
                sa.select(tables.run_event_payloads.c.event_id).where(
                    tables.run_event_payloads.c.event_id.in_([first.event_id, third.event_id])
                )
            )
        ).all()
    assert len(payloads) == 2


async def test_delayed_commit_blocks_second_writer(runtime) -> None:
    user_id, username, workspace_id, run_id, (execution_a, _execution_b) = await _setup_run_with_executions(runtime)
    factory = create_session_factory(runtime.engines[ROLE_API])
    session_a = factory()
    await session_a.begin()
    await set_scope(session_a, principal_id=user_id, workspace_id=workspace_id)
    first = await runtime.events.append(
        session_a,
        workspace_id=workspace_id,
        run_id=run_id,
        event_type="action.prepared",
        actor=username,
        execution_id=execution_a,
    )

    async def append_in_new_session() -> int:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
            appended = await runtime.events.append(
                session,
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="action.settled",
                actor=username,
                execution_id=execution_a,
            )
            return appended.run_seq

    task = asyncio.create_task(append_in_new_session())
    await asyncio.sleep(0.3)
    assert first.run_seq == 1
    assert not task.done()

    await session_a.commit()
    await session_a.close()
    second_seq = await asyncio.wait_for(task, timeout=10)
    assert second_seq == 2

    durable = await runtime.events.query_durable(workspace_id=workspace_id, principal_id=user_id, run_id=run_id)
    assert [row["run_seq"] for row in durable] == [1, 2]


async def test_rollback_leaves_no_gap(runtime) -> None:
    user_id, username, workspace_id, run_id, (execution_a, _execution_b) = await _setup_run_with_executions(runtime)
    factory = create_session_factory(runtime.engines[ROLE_API])
    session_a = factory()
    await session_a.begin()
    await set_scope(session_a, principal_id=user_id, workspace_id=workspace_id)
    await runtime.events.append(
        session_a,
        workspace_id=workspace_id,
        run_id=run_id,
        event_type="action.prepared",
        actor=username,
        execution_id=execution_a,
    )
    await session_a.rollback()
    await session_a.close()

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        appended = await runtime.events.append(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="action.prepared",
            actor=username,
            execution_id=execution_a,
        )
    assert appended.run_seq == 1
    durable = await runtime.events.query_durable(workspace_id=workspace_id, principal_id=user_id, run_id=run_id)
    assert [row["run_seq"] for row in durable] == [1]


async def test_outbox_commits_with_event_transaction(runtime) -> None:
    user_id, username, workspace_id, run_id, (execution_a, _execution_b) = await _setup_run_with_executions(runtime)
    factory = create_session_factory(runtime.engines[ROLE_API])
    session_a = factory()
    await session_a.begin()
    await set_scope(session_a, principal_id=user_id, workspace_id=workspace_id)
    await runtime.events.append(
        session_a,
        workspace_id=workspace_id,
        run_id=run_id,
        event_type="run.finalized",
        actor=username,
        execution_id=execution_a,
    )
    await runtime.events.enqueue_outbox(
        session_a,
        workspace_id=workspace_id,
        topic="run.finalized",
        dedupe_key=f"run-finalized:{run_id}",
        payload={"run_id": str(run_id)},
    )

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        before = (await session.execute(sa.select(sa.func.count()).select_from(tables.outbox_deliveries))).scalar_one()
    assert before == 0

    await session_a.commit()
    await session_a.close()
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        after = (await session.execute(sa.select(sa.func.count()).select_from(tables.outbox_deliveries))).scalar_one()
        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(
                sa.insert(tables.outbox_deliveries).values(
                    workspace_id=workspace_id,
                    topic="run.finalized",
                    dedupe_key=f"run-finalized:{run_id}",
                )
            )
    assert after == 1


async def test_notify_is_wakeup_only(runtime) -> None:
    user_id, username, workspace_id, run_id, (execution_a, _execution_b) = await _setup_run_with_executions(runtime)
    url = make_url(runtime.engines[ROLE_API].url)
    plain_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await psycopg.AsyncConnection.connect(plain_dsn, autocommit=True)
    try:
        await connection.execute(f"LISTEN {NOTIFY_CHANNEL}")
        factory = create_session_factory(runtime.engines[ROLE_API])
        session = factory()
        await session.begin()
        await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
        appended = await runtime.events.append(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="run.state_changed",
            actor=username,
            execution_id=execution_a,
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(connection.notifies()), timeout=0.5)
        await session.commit()
        await session.close()
        notification = await asyncio.wait_for(anext(connection.notifies()), timeout=5)
    finally:
        await connection.close()
    assert notification.channel == NOTIFY_CHANNEL
    assert notification.payload == f"{run_id}:{appended.run_seq}"
    assert str(workspace_id) not in notification.payload
