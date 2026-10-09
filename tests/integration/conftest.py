from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.storage.roles import ROLE_API, ROLE_EVALUATOR, ROLE_MIGRATE, ROLE_SUPERVISOR, ROLE_WORKER
from tests.support.postgres import test_db as test_db
from tests.support.replay import ReplayHarness, build_replay_harness, seed_replay_workspace
from tests.support.taskboard import TaskboardServer

HARNESS_ROLES = (ROLE_MIGRATE, ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)


@pytest_asyncio.fixture
async def harness_engines(test_db) -> AsyncIterator[dict]:
    engines = {role: create_async_engine(test_db.dsn(role), pool_size=5, max_overflow=5) for role in HARNESS_ROLES}
    yield engines
    for engine in engines.values():
        await engine.dispose()


@dataclass
class ReplayWorkspace:
    user_id: UUID
    workspace_id: UUID
    harness: ReplayHarness


@pytest_asyncio.fixture
async def replay_workspace(
    harness_engines, test_db, taskboard_server: TaskboardServer
) -> AsyncIterator[ReplayWorkspace]:
    user_id, workspace_id = await seed_replay_workspace(harness_engines)
    harness = build_replay_harness(
        engines=harness_engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
    )
    yield ReplayWorkspace(user_id=user_id, workspace_id=workspace_id, harness=harness)
    harness.aclose()


@pytest_asyncio.fixture
async def loss_workspace(harness_engines, test_db, taskboard_server: TaskboardServer) -> AsyncIterator[ReplayWorkspace]:
    user_id, workspace_id = await seed_replay_workspace(harness_engines)
    harness = build_replay_harness(
        engines=harness_engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
        fault_loss_intent="create_item",
    )
    yield ReplayWorkspace(user_id=user_id, workspace_id=workspace_id, harness=harness)
    harness.aclose()


@pytest_asyncio.fixture
async def storage_fault_workspace(
    harness_engines, test_db, taskboard_server: TaskboardServer
) -> AsyncIterator[ReplayWorkspace]:
    user_id, workspace_id = await seed_replay_workspace(harness_engines)
    harness = build_replay_harness(
        engines=harness_engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
        fault_storage=True,
    )
    yield ReplayWorkspace(user_id=user_id, workspace_id=workspace_id, harness=harness)
    harness.aclose()
