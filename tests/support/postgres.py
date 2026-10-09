from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentqa.platform.storage import tables
from agentqa.platform.storage.database import configure_event_loop_policy, create_engine, create_session_factory
from agentqa.platform.storage.migrate import upgrade
from agentqa.platform.storage.roles import (
    ROLE_API,
    ROLE_EVALUATOR,
    ROLE_MIGRATE,
    ROLE_SUPERVISOR,
    ROLE_WORKER,
    admin_dsn,
    bootstrap_profile,
    create_database,
    drop_database,
    role_dsn,
)
from agentqa.platform.storage.scope import set_scope

configure_event_loop_policy()

APP_TEST_ROLES = (ROLE_MIGRATE, ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)


@dataclass(frozen=True)
class TestDatabase:
    name: str

    def dsn(self, role: str) -> str:
        return role_dsn(role, self.name)


def _setup_session_database() -> TestDatabase:
    admin = admin_dsn()

    async def run() -> TestDatabase:
        await bootstrap_profile(admin)
        name = f"agentqa_test_{secrets.token_hex(4)}"
        await create_database(admin, name)
        await upgrade(role_dsn(ROLE_MIGRATE, name))
        return TestDatabase(name=name)

    return asyncio.run(run())


@pytest.fixture(scope="session")
def test_db() -> Iterator[TestDatabase]:
    database = _setup_session_database()
    yield database
    asyncio.run(drop_database(admin_dsn(), database.name))


@pytest_asyncio.fixture
async def role_engines(test_db: TestDatabase) -> AsyncIterator[dict[str, AsyncEngine]]:
    engines = {role: create_engine(test_db.dsn(role)) for role in APP_TEST_ROLES}
    yield engines
    for engine in engines.values():
        await engine.dispose()


@asynccontextmanager
async def scoped_transaction(
    engine: AsyncEngine, *, principal_id: UUID, workspace_id: UUID
) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
        yield session


@asynccontextmanager
async def plain_transaction(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        yield session


async def fetch_scalar(dsn: str, sql: str, params: dict | None = None) -> object:
    engine = create_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(sa.text(sql), params or {})).scalar()
    finally:
        await engine.dispose()


async def fetch_all(dsn: str, sql: str, params: dict | None = None) -> list[tuple]:
    engine = create_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(sa.text(sql), params or {})
            return [tuple(row) for row in result.all()]
    finally:
        await engine.dispose()


async def seed_user(engine: AsyncEngine, username: str | None = None) -> UUID:
    async with plain_transaction(engine) as session:
        result = await session.execute(
            sa.insert(tables.users).values(username=username or f"user-{uuid4().hex[:8]}").returning(tables.users.c.id)
        )
        return result.scalar_one()


async def seed_workspace(
    engines: dict[str, AsyncEngine], *, owner_id: UUID | None = None, label: str | None = None
) -> tuple[UUID, UUID]:
    user_id = owner_id or await seed_user(engines[ROLE_API])
    workspace_id = uuid4()
    slug = label or f"ws-{workspace_id.hex[:8]}"
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        await session.execute(sa.insert(tables.workspaces).values(id=workspace_id, slug=slug, name=slug))
        await session.execute(
            sa.insert(tables.memberships).values(workspace_id=workspace_id, user_id=user_id, role="owner")
        )
    return user_id, workspace_id


async def seed_case(
    engines: dict[str, AsyncEngine], *, principal_id: UUID, workspace_id: UUID, logical_key: str
) -> UUID:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.cases)
            .values(workspace_id=workspace_id, logical_key=logical_key)
            .returning(tables.cases.c.id)
        )
        return result.scalar_one()


async def seed_case_revision(
    engines: dict[str, AsyncEngine],
    *,
    principal_id: UUID,
    workspace_id: UUID,
    logical_key: str = "case-1",
    revision_no: int = 1,
    content_digest: str = "a" * 64,
    content: dict | None = None,
) -> tuple[UUID, UUID]:
    case_id = await seed_case(engines, principal_id=principal_id, workspace_id=workspace_id, logical_key=logical_key)
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.case_revisions)
            .values(
                workspace_id=workspace_id,
                case_id=case_id,
                revision_no=revision_no,
                content=content or {"schema_version": "case/1"},
                content_digest=content_digest,
                lifecycle="ready",
                author="tester",
            )
            .returning(tables.case_revisions.c.id)
        )
        return case_id, result.scalar_one()


async def seed_run(
    engines: dict[str, AsyncEngine], *, principal_id: UUID, workspace_id: UUID, status: str = "running"
) -> UUID:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.runs).values(workspace_id=workspace_id, status=status).returning(tables.runs.c.id)
        )
        return result.scalar_one()


async def seed_execution(
    engines: dict[str, AsyncEngine],
    *,
    principal_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    logical_key: str = "case-1",
) -> UUID:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.executions)
            .values(workspace_id=workspace_id, run_id=run_id, logical_key=logical_key)
            .returning(tables.executions.c.id)
        )
        return result.scalar_one()


async def seed_attempt(
    engines: dict[str, AsyncEngine],
    *,
    principal_id: UUID,
    workspace_id: UUID,
    execution_id: UUID,
    attempt_no: int = 1,
    fence_epoch: int = 1,
) -> UUID:
    async with scoped_transaction(
        engines[ROLE_WORKER], principal_id=principal_id, workspace_id=workspace_id
    ) as session:
        result = await session.execute(
            sa.insert(tables.attempts)
            .values(
                workspace_id=workspace_id,
                execution_id=execution_id,
                attempt_no=attempt_no,
                status="running",
                fence_epoch=fence_epoch,
            )
            .returning(tables.attempts.c.id)
        )
        return result.scalar_one()


async def seed_job(
    engines: dict[str, AsyncEngine],
    *,
    principal_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    execution_id: UUID,
    kind: str = "browser_run",
    state: str = "queued",
) -> UUID:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        result = await session.execute(
            sa.insert(tables.jobs)
            .values(
                workspace_id=workspace_id,
                run_id=run_id,
                execution_id=execution_id,
                kind=kind,
                state=state,
            )
            .returning(tables.jobs.c.id)
        )
        return result.scalar_one()
