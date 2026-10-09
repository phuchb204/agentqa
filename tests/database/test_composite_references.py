from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE
from tests.support.postgres import (
    fetch_all,
    fetch_scalar,
    scoped_transaction,
    seed_case,
    seed_run,
    seed_workspace,
)

pytestmark = pytest.mark.asyncio


async def test_case_revision_cross_workspace_rejected(role_engines: dict, test_db) -> None:
    user_a, workspace_a = await seed_workspace(role_engines)
    user_b, workspace_b = await seed_workspace(role_engines)
    case_a = await seed_case(role_engines, principal_id=user_a, workspace_id=workspace_a, logical_key="cross")
    with pytest.raises(IntegrityError):
        async with scoped_transaction(role_engines[ROLE_API], principal_id=user_b, workspace_id=workspace_b) as session:
            await session.execute(
                sa.insert(tables.case_revisions).values(
                    workspace_id=workspace_b,
                    case_id=case_a,
                    revision_no=1,
                    content={"schema_version": "case/1"},
                    content_digest="a" * 64,
                    lifecycle="ready",
                    author="tester",
                )
            )


async def test_draft_cross_workspace_case_rejected(role_engines: dict) -> None:
    user_a, workspace_a = await seed_workspace(role_engines)
    user_b, workspace_b = await seed_workspace(role_engines)
    case_a = await seed_case(role_engines, principal_id=user_a, workspace_id=workspace_a, logical_key="draft-cross")
    with pytest.raises(IntegrityError):
        async with scoped_transaction(role_engines[ROLE_API], principal_id=user_b, workspace_id=workspace_b) as session:
            await session.execute(
                sa.insert(tables.case_drafts).values(
                    workspace_id=workspace_b,
                    case_id=case_a,
                    content={"schema_version": "case/1"},
                    updated_by="tester",
                )
            )


async def test_execution_cross_workspace_run_rejected(role_engines: dict) -> None:
    user_a, workspace_a = await seed_workspace(role_engines)
    user_b, workspace_b = await seed_workspace(role_engines)
    run_a = await seed_run(role_engines, principal_id=user_a, workspace_id=workspace_a)
    with pytest.raises(IntegrityError):
        async with scoped_transaction(role_engines[ROLE_API], principal_id=user_b, workspace_id=workspace_b) as session:
            await session.execute(
                sa.insert(tables.executions).values(workspace_id=workspace_b, run_id=run_a, logical_key="cross")
            )


async def test_composite_unique_constraints_exist(test_db) -> None:
    expected = [
        "cases",
        "case_revisions",
        "case_drafts",
        "runs",
        "executions",
        "run_events",
        "credential_records",
        "artifacts",
    ]
    rows = await fetch_all(
        test_db.dsn(ROLE_MIGRATE),
        """
        SELECT rel.relname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE con.contype = 'u'
          AND con.conname = 'uq_' || rel.relname || '_workspace_id_id'
        ORDER BY rel.relname
        """,
    )
    names = [row[0] for row in rows]
    for table in expected:
        assert table in names


async def test_composite_fk_definitions_exist(test_db) -> None:
    count = await fetch_scalar(
        test_db.dsn(ROLE_MIGRATE),
        """
        SELECT count(*)
        FROM pg_constraint
        WHERE contype = 'f'
          AND conname IN (
            'fk_case_revisions_entity_workspace',
            'fk_run_snapshots_run',
            'fk_executions_run',
            'fk_attempts_execution',
            'fk_run_events_run',
            'fk_credential_grants_credential'
          )
        """,
    )
    assert count == 6
