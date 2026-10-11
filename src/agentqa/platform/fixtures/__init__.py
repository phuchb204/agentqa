from __future__ import annotations

from agentqa.platform.fixtures.canvasdesk import CanvasdeskFixture
from agentqa.platform.fixtures.canvasdesk import synthetic_password as canvasdesk_password
from agentqa.platform.fixtures.definitions import (
    CANVASDESK_FIXTURE,
    SHOPFLOW_FIXTURE,
    TASKBOARD_FIXTURE,
    FixtureDefinition,
)
from agentqa.platform.fixtures.registry import FixtureHandler, FixtureRegistry
from agentqa.platform.fixtures.shopflow import ShopflowFixture
from agentqa.platform.fixtures.shopflow import synthetic_password as shopflow_password
from agentqa.platform.fixtures.taskboard import TaskboardFixture, synthetic_password

__all__ = [
    "CANVASDESK_FIXTURE",
    "SHOPFLOW_FIXTURE",
    "TASKBOARD_FIXTURE",
    "CanvasdeskFixture",
    "FixtureDefinition",
    "FixtureHandler",
    "FixtureRegistry",
    "ShopflowFixture",
    "TaskboardFixture",
    "canvasdesk_password",
    "shopflow_password",
    "synthetic_password",
]
