from __future__ import annotations

from agentqa.platform.fixtures.definitions import TASKBOARD_FIXTURE, FixtureDefinition
from agentqa.platform.fixtures.registry import FixtureRegistry
from agentqa.platform.fixtures.taskboard import TaskboardFixture, synthetic_password

__all__ = [
    "TASKBOARD_FIXTURE",
    "FixtureDefinition",
    "FixtureRegistry",
    "TaskboardFixture",
    "synthetic_password",
]
