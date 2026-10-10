from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.platform.cli import main as cli_main
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"
ITEM_NAME = "Việc parity"


def compiled_case(name: str) -> CaseContent:
    return compile_case_document((CASE_DIR / name).read_text(encoding="utf-8")).case


def environment(taskboard_server, namespace: str, parameters: dict[str, str]) -> dict:
    return {
        "target_base_url": f"{taskboard_server.base_url}/{namespace}",
        "fixture_ref": "taskboard@1",
        "namespace": namespace,
        "parameters": parameters,
    }


async def _pat_for(harness_engines, user_id):
    from agentqa.platform.identity.sessions import TokenService

    service = TokenService(harness_engines[ROLE_API])
    issued = await service.create(user_id=user_id, name="parity", scopes=("workspace",))
    return issued.raw_token


@pytest.fixture(name="parity_api")
def parity_api_fixture(test_db):
    import asyncio
    import sys
    import threading
    import time

    import uvicorn

    from agentqa.platform.api.application import create_application
    from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
    from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.local(),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API), ROLE_WORKER: test_db.dsn(ROLE_WORKER)},
    )
    app = create_application(runtime)
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
            raise RuntimeError("parity API không khởi động")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _api_result(base_url: str, harness_engines, workspace, run_id: str) -> tuple[dict, dict]:
    from agentqa.platform.identity.sessions import SessionService

    session_service = SessionService(harness_engines[ROLE_API])
    login = await session_service.create_for_user(user_id=workspace.user_id, username="parity-ui")
    cookies = {"agentqa_session": login.raw_token}
    async with httpx.AsyncClient(base_url=base_url, cookies=cookies) as client:
        response = await client.get(f"/api/v1/workspaces/{workspace.workspace_id}/runs/{run_id}/result")
        assert response.status_code == 200, response.text
        detail = await client.get(f"/api/v1/workspaces/{workspace.workspace_id}/runs/{run_id}/detail")
        assert detail.status_code == 200, detail.text
        return response.json(), detail.json()


async def _assert_parity(
    replay_workspace,
    harness_engines,
    taskboard_server,
    parity_api: str,
    *,
    case,
    namespace,
    parameters,
    expected_verdict,
):
    from tests.support.replay import submit_case_run

    workspace = replay_workspace
    harness = workspace.harness
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, parameters),
    )
    summaries = await harness.worker.run_until_idle()
    assert len(summaries) == 1

    api_result, web_detail = await _api_result(parity_api, harness_engines, workspace, str(ids["run_id"]))
    direct = await RunReadModel(harness_engines[ROLE_API]).run_result(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"]
    )
    assert direct is not None

    import contextlib
    import io
    import os

    pat = await _pat_for(harness_engines, workspace.user_id)
    os.environ["AGENTQA_PARITY_PAT"] = pat
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = cli_main(
                [
                    "--base-url",
                    parity_api,
                    "--token-env",
                    "AGENTQA_PARITY_PAT",
                    "--json",
                    "run",
                    "result",
                    "--workspace",
                    str(workspace.workspace_id),
                    "--run",
                    str(ids["run_id"]),
                ]
            )
    finally:
        os.environ.pop("AGENTQA_PARITY_PAT", None)
    assert code in (0, 1, 2, 130)
    cli_result = json.loads(buffer.getvalue())
    assert cli_result["verdict"] == expected_verdict
    assert api_result["verdict"] == expected_verdict
    assert direct["verdict"] == expected_verdict
    assert web_detail["verdict"] == expected_verdict
    assert api_result["gate"] == direct["gate"] == cli_result["gate"] == web_detail["gate"]
    assert api_result["status"] == direct["status"] == cli_result["status"] == web_detail["status"]
    api_executions = {item["execution_id"]: item["verdict"] for item in api_result["executions"]}
    cli_executions = {item["execution_id"]: item["verdict"] for item in cli_result["executions"]}
    web_executions = {item["execution_id"]: item["verdict"] for item in web_detail["executions"]}
    assert api_executions == cli_executions == web_executions
    return ids


async def test_parity_passed_run(replay_workspace, harness_engines, taskboard_server, parity_api) -> None:
    ids = await _assert_parity(
        replay_workspace,
        harness_engines,
        taskboard_server,
        parity_api,
        case=compiled_case("login_create_item.yaml"),
        namespace="parity-pass",
        parameters={"item_name": ITEM_NAME},
        expected_verdict="passed",
    )
    assert ids["run_id"]


async def test_parity_inconclusive_run(replay_workspace, harness_engines, taskboard_server, parity_api) -> None:
    document = yaml.safe_load((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
    document["nodes"][-1]["assertions"][0]["required"] = False
    document["completion"]["required_assertions"] = []
    case = CaseContent.model_validate(document)
    await _assert_parity(
        replay_workspace,
        harness_engines,
        taskboard_server,
        parity_api,
        case=case,
        namespace="parity-inconclusive",
        parameters={"item_name": ITEM_NAME},
        expected_verdict="inconclusive",
    )


async def test_web_client_reads_same_run_state_endpoints() -> None:
    client_source = (Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "api" / "client.ts").read_text(
        encoding="utf-8"
    )
    assert "/api/v1/workspaces/{workspace_id}/runs/{run_id}" in client_source
    assert "/api/v1/workspaces/{workspace_id}/runs/{run_id}/detail" in client_source
