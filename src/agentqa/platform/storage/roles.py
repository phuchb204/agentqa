from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

ROLE_MIGRATE = "agentqa_migrate"
ROLE_API = "agentqa_api"
ROLE_WORKER = "agentqa_worker"
ROLE_SUPERVISOR = "agentqa_supervisor"
ROLE_EVALUATOR = "agentqa_evaluator"
APP_ROLES = (ROLE_MIGRATE, ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)
ORACLE_DATABASE = "agentqa_oracle"

TEST_BOOTSTRAP_DSN = "postgresql+psycopg://agentqa_bootstrap:agentqa_test_local_only@127.0.0.1:55432/postgres"
TEST_ROLE_PASSWORD = "agentqa_test_local_only"


def _test_port() -> int:
    import os

    try:
        return int(os.environ.get("AGENTQA_TEST_PGPORT", "55432"))
    except ValueError:
        return 55432


def role_dsn(
    role: str, database: str, *, password: str = TEST_ROLE_PASSWORD, host: str = "127.0.0.1", port: int | None = None
) -> str:
    resolved_port = _test_port() if port is None else port
    return f"postgresql+psycopg://{role}:{password}@{host}:{resolved_port}/{database}"


def admin_dsn(
    database: str = "postgres",
    *,
    password: str = TEST_ROLE_PASSWORD,
    host: str = "127.0.0.1",
    port: int | None = None,
) -> str:
    resolved_port = _test_port() if port is None else port
    return f"postgresql+psycopg://agentqa_bootstrap:{password}@{host}:{resolved_port}/{database}"


async def _execute_statements(dsn: str, statements: Iterable[str]) -> None:
    engine: AsyncEngine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def bootstrap_roles(dsn: str = TEST_BOOTSTRAP_DSN, *, password: str = TEST_ROLE_PASSWORD) -> None:
    statements: list[str] = []
    for role in APP_ROLES:
        statements.append(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} LOGIN PASSWORD '{password}'
                        NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS;
                ELSE
                    ALTER ROLE {role} WITH LOGIN PASSWORD '{password}'
                        NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS;
                END IF;
            END $$;
            """
        )
    await _execute_statements(dsn, statements)


async def _ensure_database(dsn: str, name: str, *, owner: str, connect_roles: Sequence[str]) -> None:
    engine: AsyncEngine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = (
                await connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name})
            ).scalar()
            if not exists:
                await connection.execute(text(f"CREATE DATABASE {name} OWNER {owner}"))
            await connection.execute(text(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC"))
            await connection.execute(text(f"REVOKE ALL ON DATABASE {name} FROM {', '.join(APP_ROLES)}"))
            await connection.execute(text(f"GRANT CONNECT ON DATABASE {name} TO {', '.join(connect_roles)}"))
    finally:
        await engine.dispose()


async def ensure_oracle_database(dsn: str = TEST_BOOTSTRAP_DSN) -> None:
    await _ensure_database(dsn, ORACLE_DATABASE, owner=ROLE_EVALUATOR, connect_roles=(ROLE_EVALUATOR, ROLE_MIGRATE))


async def bootstrap_profile(dsn: str = TEST_BOOTSTRAP_DSN, *, password: str = TEST_ROLE_PASSWORD) -> None:
    await bootstrap_roles(dsn, password=password)
    await ensure_oracle_database(dsn)


async def create_database(dsn: str, name: str, *, owner: str = ROLE_MIGRATE) -> None:
    await _ensure_database(dsn, name, owner=owner, connect_roles=APP_ROLES)


async def drop_database(dsn: str, name: str) -> None:
    statements = [
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}' AND pid <> pg_backend_pid();",
        f"DROP DATABASE IF EXISTS {name};",
    ]
    await _execute_statements(dsn, statements)
