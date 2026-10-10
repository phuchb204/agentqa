from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from tests.support.postgres import role_engines as role_engines
from tests.support.postgres import test_db as test_db

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

ORIGIN = "http://127.0.0.1:8000"


@pytest_asyncio.fixture(name="runtime")
async def runtime_fixture(test_db, tmp_path: Path) -> AsyncIterator[PlatformRuntime]:
    built = PlatformRuntime.build(
        profile=RuntimeProfile.local(),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API), ROLE_WORKER: test_db.dsn(ROLE_WORKER)},
        artifact_store=FileSystemBlobStore(tmp_path / "blobs"),
        taint=TaintRegistry(),
    )
    yield built
    await built.aclose()


@pytest_asyncio.fixture(name="api_client")
async def api_client_fixture(runtime: PlatformRuntime) -> AsyncIterator[httpx.AsyncClient]:
    app = create_application(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        yield client
