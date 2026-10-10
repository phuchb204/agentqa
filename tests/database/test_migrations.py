from __future__ import annotations

import asyncio
import secrets

import httpx
import pytest

from agentqa.platform.storage.migrate import downgrade, upgrade
from agentqa.platform.storage.roles import ROLE_MIGRATE, admin_dsn, create_database, drop_database, role_dsn
from tests.support.postgres import fetch_scalar

pytestmark = pytest.mark.asyncio

HEAD_REVISION = "0012_outbox_webhooks"
TABLE_COUNT_SQL = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
VERSION_SQL = "SELECT version_num FROM alembic_version"


def _scratch_name() -> str:
    return f"agentqa_test_mig_{secrets.token_hex(4)}"


async def test_empty_to_latest_and_rollback_restore() -> None:
    admin = admin_dsn()
    name = _scratch_name()
    dsn = role_dsn(ROLE_MIGRATE, name)
    await create_database(admin, name)
    try:
        await upgrade(dsn)
        assert await fetch_scalar(dsn, VERSION_SQL) == HEAD_REVISION
        latest_tables = await fetch_scalar(dsn, TABLE_COUNT_SQL)
        assert latest_tables is not None and latest_tables > 50

        await downgrade(dsn, "base")
        assert await fetch_scalar(dsn, TABLE_COUNT_SQL) == 0

        await upgrade(dsn)
        assert await fetch_scalar(dsn, VERSION_SQL) == HEAD_REVISION
        assert await fetch_scalar(dsn, TABLE_COUNT_SQL) == latest_tables
    finally:
        await drop_database(admin, name)


async def test_concurrent_upgrade_serializes_on_lock() -> None:
    admin = admin_dsn()
    name = _scratch_name()
    dsn = role_dsn(ROLE_MIGRATE, name)
    await create_database(admin, name)
    try:
        await asyncio.gather(upgrade(dsn), upgrade(dsn))
        assert await fetch_scalar(dsn, VERSION_SQL) == HEAD_REVISION
        count = await fetch_scalar(dsn, TABLE_COUNT_SQL)
        assert count is not None and count > 50
    finally:
        await drop_database(admin, name)


async def test_rerun_upgrade_is_noop() -> None:
    admin = admin_dsn()
    name = _scratch_name()
    dsn = role_dsn(ROLE_MIGRATE, name)
    await create_database(admin, name)
    try:
        await upgrade(dsn)
        first = await fetch_scalar(dsn, TABLE_COUNT_SQL)
        await upgrade(dsn)
        assert await fetch_scalar(dsn, TABLE_COUNT_SQL) == first
        assert await fetch_scalar(dsn, VERSION_SQL) == HEAD_REVISION
    finally:
        await drop_database(admin, name)


async def test_request_path_does_not_run_migrations() -> None:
    admin = admin_dsn()
    name = _scratch_name()
    await create_database(admin, name)
    try:
        from agentqa.platform.api.application import api

        transport = httpx.ASGITransport(app=api)
        async with httpx.AsyncClient(transport=transport, base_url="http://agentqa.test") as client:
            response = await client.get("/health/live")
        assert response.status_code == 200
        assert await fetch_scalar(admin_dsn(name), TABLE_COUNT_SQL) == 0
    finally:
        await drop_database(admin, name)
