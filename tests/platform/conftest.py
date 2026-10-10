from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest_asyncio
from tests.support.authoring import ScriptedAuthoringGo
from tests.support.exploration import FakeSitePort, default_site
from tests.support.postgres import role_engines as role_engines
from tests.support.postgres import test_db as test_db
from tests.support.security import create_user, create_workspace, login

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

ORIGIN = "http://127.0.0.1:8000"


@pytest_asyncio.fixture(name="authoring_model")
def authoring_model_fixture() -> ScriptedAuthoringGo:
    return ScriptedAuthoringGo()


@pytest_asyncio.fixture(name="exploration_port")
def exploration_port_fixture() -> FakeSitePort:
    return FakeSitePort(default_site())


@pytest_asyncio.fixture(name="runtime")
async def runtime_fixture(
    test_db, tmp_path, authoring_model: ScriptedAuthoringGo, exploration_port: FakeSitePort
) -> AsyncIterator[PlatformRuntime]:
    built = PlatformRuntime.build(
        profile=RuntimeProfile.local(),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API), ROLE_WORKER: test_db.dsn(ROLE_WORKER)},
        artifact_store=FileSystemBlobStore(tmp_path / "blobs"),
        taint=TaintRegistry(),
        generative_model=authoring_model,
        exploration_port=exploration_port,
    )
    yield built
    await built.aclose()


@pytest_asyncio.fixture(name="api_client")
async def api_client_fixture(runtime: PlatformRuntime) -> AsyncIterator[httpx.AsyncClient]:
    app = create_application(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        yield client


@pytest_asyncio.fixture(name="owner")
async def owner_fixture(runtime: PlatformRuntime, api_client: httpx.AsyncClient) -> tuple[str, str]:
    _user_id, username = await create_user(runtime, "owner", "pw-123456")
    csrf = await login(api_client, username, "pw-123456")
    workspace_id = await create_workspace(api_client, csrf, f"ws-{uuid4().hex[:8]}")
    return workspace_id, csrf
