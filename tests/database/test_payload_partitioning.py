from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE, ROLE_WORKER
from tests.support.postgres import (
    fetch_all,
    scoped_transaction,
    seed_execution,
    seed_run,
    seed_workspace,
)

pytestmark = pytest.mark.asyncio

OCTOBER = date(2026, 10, 1)
NOVEMBER = date(2026, 11, 1)


async def _seed_event(
    engines: dict,
    *,
    principal_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    run_seq: int,
    execution_id: UUID | None = None,
    execution_seq: int | None = None,
    month: date = OCTOBER,
) -> UUID:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.run_events)
            .values(
                workspace_id=workspace_id,
                run_id=run_id,
                run_seq=run_seq,
                execution_id=execution_id,
                execution_seq=execution_seq,
                type="action.settled",
                actor="worker",
                payload_month=month,
            )
            .returning(tables.run_events.c.id)
        )
        return result.scalar_one()


async def _insert_payload(
    engines: dict, *, principal_id: UUID, workspace_id: UUID, event_id: UUID, month: date, payload: dict
) -> None:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        await session.execute(
            sa.insert(tables.run_event_payloads).values(event_id=event_id, payload_month=month, payload=payload)
        )


async def test_payload_partitions_exist(test_db) -> None:
    rows = await fetch_all(
        test_db.dsn(ROLE_MIGRATE),
        """
        SELECT child.relname
        FROM pg_inherits
        JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
        JOIN pg_class child ON child.oid = pg_inherits.inhrelid
        WHERE parent.relname IN ('run_event_payloads', 'model_call_payloads')
        """,
    )
    names = {row[0] for row in rows}
    for parent in ("run_event_payloads", "model_call_payloads"):
        assert f"{parent}_p202610" in names
        assert f"{parent}_p202611" in names
        assert f"{parent}_default" in names


async def test_duplicate_payload_same_month_rejected(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    event_id = await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=1)
    await _insert_payload(
        role_engines, principal_id=principal, workspace_id=workspace, event_id=event_id, month=OCTOBER, payload={"a": 1}
    )
    with pytest.raises(IntegrityError):
        await _insert_payload(
            role_engines,
            principal_id=principal,
            workspace_id=workspace,
            event_id=event_id,
            month=OCTOBER,
            payload={"a": 2},
        )


async def test_payload_wrong_month_rejected_by_header_fk(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    event_id = await _seed_event(
        role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=1, month=OCTOBER
    )
    with pytest.raises(IntegrityError):
        await _insert_payload(
            role_engines,
            principal_id=principal,
            workspace_id=workspace,
            event_id=event_id,
            month=NOVEMBER,
            payload={"a": 1},
        )


async def test_run_seq_is_globally_unique(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=1)
    with pytest.raises(IntegrityError):
        await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=1)
    with pytest.raises(IntegrityError):
        await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=0)


async def test_execution_seq_unique_when_present(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    execution_id = await seed_execution(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id)
    await _seed_event(
        role_engines,
        principal_id=principal,
        workspace_id=workspace,
        run_id=run_id,
        run_seq=1,
        execution_id=execution_id,
        execution_seq=1,
    )
    with pytest.raises(IntegrityError):
        await _seed_event(
            role_engines,
            principal_id=principal,
            workspace_id=workspace,
            run_id=run_id,
            run_seq=2,
            execution_id=execution_id,
            execution_seq=1,
        )
    await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=3)
    await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=4)


async def test_active_job_and_lease_uniqueness(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    execution_id = await seed_execution(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        job_id = (
            await session.execute(
                sa.insert(tables.jobs)
                .values(workspace_id=workspace, run_id=run_id, execution_id=execution_id, kind="browser_run")
                .returning(tables.jobs.c.id)
            )
        ).scalar_one()

    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.update(tables.jobs).where(tables.jobs.c.id == job_id).values(state="claimed", claimed_by="worker-1")
        )
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                sa.insert(tables.jobs).values(
                    workspace_id=workspace,
                    run_id=run_id,
                    execution_id=execution_id,
                    kind="browser_run",
                    state="claimed",
                )
            )

    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.worker_leases).values(
                workspace_id=workspace,
                job_id=job_id,
                worker_id="worker-1",
                epoch=1,
                expires_at=sa.func.now() + sa.text("interval '30 seconds'"),
            )
        )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                sa.insert(tables.worker_leases).values(
                    workspace_id=workspace,
                    job_id=job_id,
                    worker_id="worker-2",
                    epoch=1,
                    expires_at=sa.func.now() + sa.text("interval '30 seconds'"),
                )
            )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.update(tables.worker_leases)
            .where(tables.worker_leases.c.job_id == job_id)
            .values(released_at=sa.func.now())
        )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.worker_leases).values(
                workspace_id=workspace,
                job_id=job_id,
                worker_id="worker-2",
                epoch=2,
                expires_at=sa.func.now() + sa.text("interval '30 seconds'"),
            )
        )


async def test_model_call_payload_duplicate_and_month(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        call_id = (
            await session.execute(
                sa.insert(tables.model_calls)
                .values(
                    workspace_id=workspace,
                    purpose="decide",
                    requested_model="deepseek-v4.1-flash",
                    route="opencode_go",
                    payload_month=OCTOBER,
                )
                .returning(tables.model_calls.c.id)
            )
        ).scalar_one()
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.model_call_payloads).values(
                call_id=call_id, payload_month=OCTOBER, payload={"request": "synthetic"}
            )
        )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                sa.insert(tables.model_call_payloads).values(
                    call_id=call_id, payload_month=OCTOBER, payload={"request": "duplicate"}
                )
            )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                sa.insert(tables.model_call_payloads).values(
                    call_id=call_id, payload_month=NOVEMBER, payload={"request": "wrong-month"}
                )
            )


async def test_events_without_execution_allow_multiple(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=1)
    await _seed_event(role_engines, principal_id=principal, workspace_id=workspace, run_id=run_id, run_seq=2)
