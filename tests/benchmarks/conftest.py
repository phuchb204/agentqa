from __future__ import annotations

from collections.abc import Iterator

import pytest

from agentqa.platform.fixtures import CanvasdeskFixture, FixtureRegistry, ShopflowFixture, TaskboardFixture
from tests.integration.conftest import (
    ReplayWorkspace,
)
from tests.integration.conftest import (
    agent_workspace_factory as agent_workspace_factory,
)
from tests.integration.conftest import (
    harness_engines as harness_engines,
)
from tests.integration.conftest import (
    replay_workspace as replay_workspace,
)
from tests.support.canvasdesk import CanvasdeskServer, build_canvasdesk_fixture, start_canvasdesk_server
from tests.support.postgres import test_db as test_db
from tests.support.shopflow import ShopflowServer, build_shopflow_fixture, start_shopflow_server
from tests.support.taskboard import TaskboardServer

__all__ = ["ReplayWorkspace"]


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


@pytest.fixture(name="benchmark_registry")
def benchmark_registry_fixture(
    taskboard_server: TaskboardServer,
    shopflow_server: ShopflowServer,
    canvasdesk_server: CanvasdeskServer,
) -> FixtureRegistry:
    registry = FixtureRegistry()
    registry.register(TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token))
    registry.register(ShopflowFixture(shopflow_server.base_url, shopflow_server.control_token))
    registry.register(CanvasdeskFixture(canvasdesk_server.base_url, canvasdesk_server.control_token))
    return registry
