from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from agentqa.platform.fixtures import FixtureRegistry, TaskboardFixture
from tests.support.network_guard import PROVIDER_ENV_VARS, install_network_guard, strip_provider_env
from tests.support.taskboard import TaskboardServer, start_taskboard_server


def pytest_configure(config: pytest.Config) -> None:
    strip_provider_env()
    install_network_guard()


@pytest.fixture(scope="session")
def taskboard_server() -> Iterator[TaskboardServer]:
    with start_taskboard_server() as server:
        yield server


@pytest.fixture()
def fixture_registry(taskboard_server: TaskboardServer) -> FixtureRegistry:
    registry = FixtureRegistry()
    registry.register(TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token))
    return registry


@pytest.fixture(autouse=True)
def provider_environment_is_stripped() -> None:
    leaked = [name for name in PROVIDER_ENV_VARS if name in os.environ]
    assert leaked == [], f"provider variables leaked into the test environment: {leaked}"
