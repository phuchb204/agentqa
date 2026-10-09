from __future__ import annotations

import pytest_asyncio

from tests.support.faults import FaultEnv, build_fault_env
from tests.support.postgres import role_engines as role_engines
from tests.support.postgres import test_db as test_db


@pytest_asyncio.fixture
async def fault_env(role_engines, test_db) -> FaultEnv:
    from agentqa.platform.storage.roles import ROLE_SUPERVISOR, ROLE_WORKER

    return await build_fault_env(
        role_engines,
        test_db.dsn(ROLE_SUPERVISOR),
        test_db.dsn(ROLE_WORKER),
    )
