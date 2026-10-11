from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.fixtures import CanvasdeskFixture, ShopflowFixture, TaskboardFixture
from agentqa.platform.storage.roles import ROLE_API, ROLE_EVALUATOR, ROLE_MIGRATE, ROLE_SUPERVISOR, ROLE_WORKER
from tests.support.canvasdesk import CanvasdeskServer, build_canvasdesk_fixture, start_canvasdesk_server
from tests.support.postgres import test_db as test_db
from tests.support.shopflow import ShopflowServer, build_shopflow_fixture, start_shopflow_server
from tests.support.taskboard import TaskboardServer

__all__ = ["test_db"]

HARNESS_ROLES = (ROLE_MIGRATE, ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)


@pytest.fixture(scope="session", name="shopflow_server")
def shopflow_server_fixture() -> Iterator[ShopflowServer]:
    with start_shopflow_server() as server:
        yield server


@pytest.fixture(scope="session", name="canvasdesk_server")
def canvasdesk_server_fixture() -> Iterator[CanvasdeskServer]:
    with start_canvasdesk_server() as server:
        yield server


@pytest.fixture(name="shopflow_fixture")
def shopflow_fixture_client(shopflow_server: ShopflowServer) -> ShopflowFixture:
    return build_shopflow_fixture(shopflow_server)


@pytest.fixture(name="canvasdesk_fixture")
def canvasdesk_fixture_client(canvasdesk_server: CanvasdeskServer) -> CanvasdeskFixture:
    return build_canvasdesk_fixture(canvasdesk_server)


@pytest.fixture(name="taskboard_fixture")
def taskboard_fixture_client(taskboard_server: TaskboardServer) -> TaskboardFixture:
    return TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)


@pytest_asyncio.fixture(name="role_engines")
async def role_engines_fixture(test_db) -> AsyncIterator[dict]:
    engines = {role: create_async_engine(test_db.dsn(role), pool_size=5, max_overflow=5) for role in HARNESS_ROLES}
    yield engines
    for engine in engines.values():
        await engine.dispose()
