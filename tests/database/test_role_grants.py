from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_engine
from agentqa.platform.storage.roles import (
    APP_ROLES,
    ORACLE_DATABASE,
    ROLE_API,
    ROLE_EVALUATOR,
    ROLE_MIGRATE,
    ROLE_WORKER,
    role_dsn,
)
from tests.support.postgres import (
    fetch_all,
    scoped_transaction,
    seed_case_revision,
    seed_run,
    seed_user,
    seed_workspace,
)

pytestmark = pytest.mark.asyncio


async def _can_connect(dsn: str) -> bool:
    engine = create_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text("SELECT 1"))
        return True
    except DBAPIError:
        return False
    finally:
        await engine.dispose()


async def test_app_roles_have_no_privilege_escalation(test_db) -> None:
    rows = await fetch_all(
        test_db.dsn(ROLE_MIGRATE),
        "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = ANY(:names)",
        {"names": list(APP_ROLES)},
    )
    assert len(rows) == len(APP_ROLES)
    for _name, superuser, bypass, createdb, createrole in rows:
        assert superuser is False
        assert bypass is False
        assert createdb is False
        assert createrole is False


async def test_worker_and_api_cannot_connect_oracle(test_db) -> None:
    assert await _can_connect(role_dsn(ROLE_WORKER, ORACLE_DATABASE)) is False
    assert await _can_connect(role_dsn(ROLE_API, ORACLE_DATABASE)) is False
    assert await _can_connect(role_dsn(ROLE_EVALUATOR, ORACLE_DATABASE)) is True


async def test_worker_cannot_insert_ready_content(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    case_id, _revision_id = await seed_case_revision(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                sa.insert(tables.case_revisions).values(
                    workspace_id=workspace,
                    case_id=case_id,
                    revision_no=2,
                    content={"schema_version": "case/1"},
                    content_digest="b" * 64,
                    lifecycle="ready",
                    author="worker",
                )
            )
    assert "permission denied" in str(error.value)


async def test_api_cannot_delete_rows(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    await seed_case_revision(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(sa.delete(tables.cases))
    assert "permission denied" in str(error.value)


async def test_ready_revision_content_is_immutable(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    _case_id, revision_id = await seed_case_revision(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=principal, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError) as update_error:
            await session.execute(
                sa.update(tables.case_revisions)
                .where(tables.case_revisions.c.id == revision_id)
                .values(content={"changed": True})
            )
        assert "agentqa_revision_immutable" in str(update_error.value)
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=principal, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError) as delete_error:
            await session.execute(sa.delete(tables.case_revisions).where(tables.case_revisions.c.id == revision_id))
        assert "agentqa_revision_immutable" in str(delete_error.value)


async def test_lifecycle_archive_is_allowed(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    _case_id, revision_id = await seed_case_revision(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=principal, workspace_id=workspace
    ) as session:
        await session.execute(
            sa.update(tables.case_revisions)
            .where(tables.case_revisions.c.id == revision_id)
            .values(lifecycle="archived", archived_at=sa.func.now())
        )


async def test_run_events_are_append_only(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        result = await session.execute(
            sa.insert(tables.run_events)
            .values(
                workspace_id=workspace,
                run_id=run_id,
                run_seq=1,
                type="run.state_changed",
                actor="api",
                payload_month=sa.func.current_date(),
            )
            .returning(tables.run_events.c.id)
        )
        event_id = result.scalar_one()
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=principal, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError) as update_error:
            await session.execute(
                sa.update(tables.run_events).where(tables.run_events.c.id == event_id).values(actor="tampered")
            )
        assert "agentqa_append_only" in str(update_error.value)
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=principal, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError) as delete_error:
            await session.execute(sa.delete(tables.run_events).where(tables.run_events.c.id == event_id))
        assert "agentqa_append_only" in str(delete_error.value)


async def test_owner_last_membership_invariant(role_engines: dict) -> None:
    user_id, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(role_engines[ROLE_MIGRATE], principal_id=user_id, workspace_id=workspace) as session:
        with pytest.raises(DBAPIError) as delete_error:
            await session.execute(sa.delete(tables.memberships).where(tables.memberships.c.workspace_id == workspace))
        assert "agentqa_owner_last" in str(delete_error.value)

    second_user = await seed_user(role_engines[ROLE_API])
    async with scoped_transaction(role_engines[ROLE_API], principal_id=user_id, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.memberships).values(workspace_id=workspace, user_id=second_user, role="owner")
        )
    async with scoped_transaction(role_engines[ROLE_MIGRATE], principal_id=user_id, workspace_id=workspace) as session:
        await session.execute(
            sa.delete(tables.memberships).where(
                tables.memberships.c.workspace_id == workspace, tables.memberships.c.user_id == user_id
            )
        )
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=second_user, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError) as demote_error:
            await session.execute(
                sa.update(tables.memberships)
                .where(tables.memberships.c.workspace_id == workspace)
                .values(role="editor")
            )
        assert "agentqa_owner_last" in str(demote_error.value)


async def test_worker_cannot_update_run_snapshots(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    run_id = await seed_run(role_engines, principal_id=principal, workspace_id=workspace)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        await session.execute(
            sa.insert(tables.run_snapshots).values(
                workspace_id=workspace,
                run_id=run_id,
                snapshot_version=1,
                content={"policy": "default"},
                content_digest="c" * 64,
            )
        )
    async with scoped_transaction(role_engines[ROLE_WORKER], principal_id=principal, workspace_id=workspace) as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(sa.update(tables.run_snapshots).values(content={"tampered": True}))
    assert "permission denied" in str(error.value)


async def test_supervisor_has_no_write_outside_controls(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    from agentqa.platform.storage.roles import ROLE_SUPERVISOR

    async with scoped_transaction(
        role_engines[ROLE_SUPERVISOR], principal_id=principal, workspace_id=workspace
    ) as session:
        with pytest.raises(DBAPIError):
            await session.execute(sa.insert(tables.cases).values(workspace_id=workspace, logical_key=str(uuid4())))
