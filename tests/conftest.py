from __future__ import annotations

import os

import pytest

from tests.support.network_guard import PROVIDER_ENV_VARS, install_network_guard, strip_provider_env


def pytest_configure(config: pytest.Config) -> None:
    strip_provider_env()
    install_network_guard()


@pytest.fixture(autouse=True)
def provider_environment_is_stripped() -> None:
    leaked = [name for name in PROVIDER_ENV_VARS if name in os.environ]
    assert leaked == [], f"provider variables leaked into the test environment: {leaked}"
