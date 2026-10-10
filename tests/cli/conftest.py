from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
import uvicorn
from tests.support.platform import service_case_revision, service_workspace
from tests.support.postgres import role_engines as role_engines
from tests.support.postgres import test_db as test_db

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER


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


@pytest_asyncio.fixture(name="cli_server")
async def cli_server_fixture(test_db, tmp_path: Path) -> AsyncIterator[str]:
    server_runtime = PlatformRuntime.build(
        profile=RuntimeProfile.local(),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API), ROLE_WORKER: test_db.dsn(ROLE_WORKER)},
        artifact_store=FileSystemBlobStore(tmp_path / "server-blobs"),
        taint=TaintRegistry(),
    )
    app = create_application(server_runtime)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    def thread_main() -> None:
        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(server.serve())
            finally:
                loop.close()
        else:
            server.run()

    thread = threading.Thread(target=thread_main, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("CLI test server không khởi động")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        await server_runtime.aclose()


@pytest_asyncio.fixture(name="cli_env")
async def cli_env_fixture(runtime: PlatformRuntime, cli_server: str, monkeypatch) -> dict:
    user_id, username, workspace_id = await service_workspace(runtime)
    case = await service_case_revision(
        runtime, workspace_id=workspace_id, principal_id=user_id, actor=username, logical_key="cli_case"
    )
    issued = await runtime.tokens.create(user_id=user_id, name="cli", scopes=("workspace",))
    monkeypatch.setenv("AGENTQA_TOKEN", issued.raw_token)
    return {
        "runtime": runtime,
        "base_url": cli_server,
        "user_id": user_id,
        "username": username,
        "workspace_id": str(workspace_id),
        "case_revision_id": str(case.revision_id),
        "token": issued.raw_token,
    }
