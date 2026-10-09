from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_engine, create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE
from agentqa.platform.storage.scope import WORKSPACE_SETTING, set_scope
from tests.support.postgres import (
    plain_transaction,
    scoped_transaction,
    seed_case,
    seed_workspace,
)

pytestmark = pytest.mark.asyncio


async def test_select_without_scope_returns_nothing(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    await seed_case(role_engines, principal_id=principal, workspace_id=workspace, logical_key="visible")
    async with plain_transaction(role_engines[ROLE_API]) as session:
        rows = (await session.execute(sa.select(tables.cases.c.id))).all()
    assert rows == []


async def test_insert_without_scope_is_denied(role_engines: dict) -> None:
    with pytest.raises(DBAPIError) as error:
        async with plain_transaction(role_engines[ROLE_API]) as session:
            await session.execute(sa.insert(tables.cases).values(workspace_id=uuid4(), logical_key="no-scope"))
    assert "row-level security" in str(error.value)


async def test_insert_without_principal_is_denied(role_engines: dict) -> None:
    _principal, workspace = await seed_workspace(role_engines)
    with pytest.raises(DBAPIError) as error:
        factory = create_session_factory(role_engines[ROLE_API])
        async with factory() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config(:name, :value, true)"),
                {"name": WORKSPACE_SETTING, "value": str(workspace)},
            )
            await session.execute(sa.insert(tables.cases).values(workspace_id=workspace, logical_key="no-principal"))
    assert "row-level security" in str(error.value)


async def test_pooled_connection_scope_reset(test_db, role_engines: dict) -> None:
    engine = create_engine(test_db.dsn(ROLE_API), pool_size=1, max_overflow=0)
    try:
        principal, workspace = await seed_workspace(role_engines)
        await seed_case(role_engines, principal_id=principal, workspace_id=workspace, logical_key="pooled")
        async with scoped_transaction(engine, principal_id=principal, workspace_id=workspace) as session:
            visible = (await session.execute(sa.select(tables.cases.c.id))).all()
            assert len(visible) == 1
        async with plain_transaction(engine) as session:
            leaked = (await session.execute(sa.select(tables.cases.c.id))).all()
            settings = (
                await session.execute(
                    sa.text(
                        "SELECT current_setting('agentqa.principal_id', true), "
                        "current_setting('agentqa.workspace_id', true)"
                    )
                )
            ).one()
        assert leaked == []
        assert settings[0] in (None, "")
        assert settings[1] in (None, "")
    finally:
        await engine.dispose()


async def test_cross_workspace_rows_hidden(role_engines: dict) -> None:
    user_a, workspace_a = await seed_workspace(role_engines)
    _user_b, workspace_b = await seed_workspace(role_engines)
    await seed_case(role_engines, principal_id=user_a, workspace_id=workspace_a, logical_key="hidden")
    async with scoped_transaction(role_engines[ROLE_API], principal_id=user_a, workspace_id=workspace_b) as session:
        rows = (await session.execute(sa.select(tables.cases.c.id))).all()
    assert rows == []


async def test_force_rls_applies_to_table_owner(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    await seed_case(role_engines, principal_id=principal, workspace_id=workspace, logical_key="owner-check")
    other_principal, other_workspace = await seed_workspace(role_engines)
    async with scoped_transaction(
        role_engines[ROLE_MIGRATE], principal_id=other_principal, workspace_id=other_workspace
    ) as session:
        scoped_rows = (await session.execute(sa.select(tables.cases.c.id))).all()
    async with plain_transaction(role_engines[ROLE_MIGRATE]) as session:
        unscoped_rows = (await session.execute(sa.select(tables.cases.c.id))).all()
    assert scoped_rows == []
    assert unscoped_rows == []


async def test_workspace_policy_scopes_workspaces_table(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    await seed_workspace(role_engines)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        rows = (await session.execute(sa.select(tables.workspaces.c.id))).all()
    assert rows == [(workspace,)]


async def test_set_scope_roundtrip(role_engines: dict) -> None:
    principal, workspace = await seed_workspace(role_engines)
    factory = create_session_factory(role_engines[ROLE_API])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=principal, workspace_id=workspace)
        value = (await session.execute(sa.text("SELECT current_setting('agentqa.workspace_id', true)"))).scalar()
        assert value == str(workspace)
