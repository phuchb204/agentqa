from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from tests.support.postgres import (
    scoped_transaction,
    seed_attempt,
    seed_execution,
    seed_job,
    seed_run,
    seed_workspace,
)

from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.worker_daemon import WorkerDaemon
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_SUPERVISOR, ROLE_WORKER

pytestmark = pytest.mark.asyncio


def _daemon(test_db, *, workspace_id: UUID, principal_id: UUID) -> WorkerDaemon:
    return WorkerDaemon(
        dsn_by_role={
            ROLE_API: test_db.dsn(ROLE_API),
            ROLE_WORKER: test_db.dsn(ROLE_WORKER),
            ROLE_SUPERVISOR: test_db.dsn(ROLE_SUPERVISOR),
        },
        workspace_id=workspace_id,
        principal_id=principal_id,
        maintenance_only=True,
        poll_seconds=0.05,
    )


async def _seed_active_run(engines) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    user_id, workspace_id = await seed_workspace(engines, label="drain")
    run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id, status="running")
    execution_id = await seed_execution(
        engines, principal_id=user_id, workspace_id=workspace_id, run_id=run_id, logical_key="drain-case"
    )
    attempt_id = await seed_attempt(engines, principal_id=user_id, workspace_id=workspace_id, execution_id=execution_id)
    job_id = await seed_job(
        engines,
        principal_id=user_id,
        workspace_id=workspace_id,
        run_id=run_id,
        execution_id=execution_id,
        state="claimed",
    )
    return user_id, workspace_id, run_id, attempt_id, job_id


async def test_stale_lease_is_quarantined_with_reason(role_engines, test_db) -> None:
    engines = role_engines
    user_id, workspace_id, run_id, _attempt, job_id = await _seed_active_run(engines)
    queue = JobQueue(
        create_session_factory(engines[ROLE_WORKER]),
        workspace_id=workspace_id,
        principal_id=user_id,
    )
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        await session.execute(sa.update(tables.jobs).where(tables.jobs.c.id == job_id).values(state="queued"))
    claim = await queue.claim("worker-1", lease_seconds=1)
    assert claim is not None
    await asyncio.sleep(1.3)

    daemon = _daemon(test_db, workspace_id=workspace_id, principal_id=user_id)
    await daemon.start()
    try:
        quarantined = await daemon.quarantine_stale()
    finally:
        await daemon.close()
    assert claim.job_id in quarantined

    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        job = (
            await session.execute(
                sa.select(tables.jobs.c.state, tables.jobs.c.payload).where(tables.jobs.c.id == claim.job_id)
            )
        ).one()
        run = (
            await session.execute(
                sa.select(tables.runs.c.status, tables.runs.c.reasons).where(tables.runs.c.id == run_id)
            )
        ).one()
        execution = (
            await session.execute(sa.select(tables.executions.c.status).where(tables.executions.c.run_id == run_id))
        ).one()
        lease = (
            await session.execute(
                sa.select(tables.worker_leases.c.released_at).where(tables.worker_leases.c.id == claim.lease_id)
            )
        ).one()
    assert job.state == "quarantined"
    assert job.payload["quarantine_reason"] == "restart_quarantine"
    assert run.status == "error"
    assert any(reason.startswith("quarantined:") for reason in run.reasons)
    assert execution.status == "error"
    assert lease.released_at is not None


async def test_drain_stops_worker_loop_quickly(role_engines, test_db) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="drain-loop")
    daemon = _daemon(test_db, workspace_id=workspace_id, principal_id=user_id)
    await daemon.start()
    try:
        task = asyncio.create_task(daemon.run_forever())
        await asyncio.sleep(0.2)
        await daemon.drain()
        await asyncio.wait_for(task, timeout=5)
        assert daemon._stop.is_set()
    finally:
        await daemon.close()


async def test_version_mismatch_quarantines_and_waits(test_db) -> None:
    import secrets

    from agentqa.platform.storage.migrate import downgrade, upgrade
    from agentqa.platform.storage.roles import ROLE_MIGRATE, admin_dsn, create_database, drop_database, role_dsn

    name = f"agentqa_test_drain_{secrets.token_hex(4)}"
    admin = admin_dsn()
    await create_database(admin, name)
    engines = {
        role: create_async_engine(role_dsn(role, name))
        for role in (ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_MIGRATE)
    }
    try:
        await upgrade(role_dsn(ROLE_MIGRATE, name))
        user_id, workspace_id, run_id, _attempt, job_id = await _seed_active_run(engines)
        async with scoped_transaction(engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id) as session:
            await session.execute(
                sa.insert(tables.worker_leases).values(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    worker_id="stale-worker",
                    epoch=1,
                    expires_at=sa.text("now() - interval '1 hour'"),
                )
            )
        await downgrade(role_dsn(ROLE_MIGRATE, name), "-1")

        daemon = WorkerDaemon(
            dsn_by_role={
                ROLE_API: role_dsn(ROLE_API, name),
                ROLE_WORKER: role_dsn(ROLE_WORKER, name),
                ROLE_SUPERVISOR: role_dsn(ROLE_SUPERVISOR, name),
            },
            workspace_id=workspace_id,
            principal_id=user_id,
            maintenance_only=True,
            poll_seconds=0.05,
        )
        await daemon.start()
        try:
            task = asyncio.create_task(daemon.run_forever())
            await asyncio.sleep(0.4)
            await daemon.drain()
            await asyncio.wait_for(task, timeout=5)
        finally:
            await daemon.close()

        async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
            job = (
                await session.execute(
                    sa.select(tables.jobs.c.state, tables.jobs.c.payload).where(tables.jobs.c.id == job_id)
                )
            ).one()
            run = (await session.execute(sa.select(tables.runs.c.status).where(tables.runs.c.id == run_id))).one()
        assert job.state == "quarantined"
        assert job.payload["quarantine_reason"] == "version_mismatch"
        assert run.status == "error"
    finally:
        for engine in engines.values():
            await engine.dispose()
        await drop_database(admin, name)
