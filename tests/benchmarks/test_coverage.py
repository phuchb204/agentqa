from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from tools.check_benchmark_inventory import run as run_inventory

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API
from agentqa.platform.storage.scope import set_scope
from agentqa.platform.usage.service import UsageLedgerService
from tests.integration.conftest import ReplayWorkspace
from tests.support.canvasdesk import CanvasdeskServer
from tests.support.replay import build_replay_harness, seed_replay_workspace, submit_case_run
from tests.support.taskboard import TaskboardServer

REPO_ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = REPO_ROOT / "benchmarks" / "public" / "cases" / "taskboard"
BASELINE_DIR = REPO_ROOT / "benchmarks" / "public" / "baselines" / "plans" / "taskboard"
ITEM_NAME = "Việc parity"

USAGE_BUCKET_KEYS = {"calls", "settled", "unknown", "input_tokens", "output_tokens", "cached_tokens"}
WALL_TIME_KEYS = {"wall_time_seconds", "unknown_intervals"}


def test_inventory_reports_no_gaps_and_covers_required_groups() -> None:
    gaps, summary = run_inventory(REPO_ROOT)
    assert gaps.items == [], gaps.items
    assert summary["cohorts"].get("transactional", 0) >= 1
    assert summary["cohorts"].get("async", 0) >= 1
    assert summary["cohorts"].get("visual", 0) >= 1
    assert summary["error_kinds"].get("business_failure", 0) >= 1
    assert summary["error_kinds"].get("validation_rejected", 0) >= 1
    assert summary["error_kinds"].get("async_unknown", 0) >= 1
    for group in ("navigate", "form_input", "pointer", "selection", "scroll", "upload_download", "frame_tab", "wait"):
        assert summary["action_groups"].get(group, 0) >= 1, group
    for group in ("presence", "text_value", "attributes_state", "counts", "network", "download", "visual"):
        assert summary["evaluator_groups"].get(group, 0) >= 1, group


def compiled_baseline(name: str) -> CaseContent:
    return compile_case_document((BASELINE_DIR / name).read_text(encoding="utf-8")).case


def environment(taskboard_server: TaskboardServer, namespace: str, parameters: dict[str, str]) -> dict:
    return {
        "target_base_url": f"{taskboard_server.base_url}/{namespace}",
        "fixture_ref": "taskboard@1",
        "namespace": namespace,
        "parameters": parameters,
    }


def success_plan() -> dict:
    return {
        "go": [
            {"operation": "navigate", "intent": "open_login", "value": {"kind": "literal", "value": "/login"}},
            {"operation": "fill", "intent": "login_username", "match": {"role": "textbox", "name": "Tài khoản"}},
            {"operation": "fill", "intent": "login_password", "match": {"role": "textbox", "name": "Mật khẩu"}},
            {"operation": "click", "intent": "login_submit", "match": {"role": "button", "name": "Đăng nhập"}},
            {"operation": "fill", "intent": "new_item", "match": {"role": "textbox", "name": "Việc mới"}},
            {"operation": "click", "intent": "create_item", "match": {"role": "button", "name": "Thêm việc"}},
            {"raw": {"decision": "stop", "rationale": "script complete"}},
        ]
    }


async def usage_snapshot(engines, workspace: ReplayWorkspace, run_id):
    usage = UsageLedgerService()
    factory = create_session_factory(engines[ROLE_API])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=workspace.user_id, workspace_id=workspace.workspace_id)
        phases = await usage.usage_by_phase(session, workspace_id=workspace.workspace_id, run_id=run_id)
        wall = await usage.wall_time_seconds(session, workspace_id=workspace.workspace_id, run_id=run_id)
        aggregate = await usage.aggregate_run(session, workspace_id=workspace.workspace_id, run_id=run_id)
    return phases, wall, aggregate


@pytest.mark.asyncio
async def test_static_baseline_and_agent_share_telemetry_accounting(
    replay_workspace: ReplayWorkspace,
    agent_workspace_factory,
    taskboard_server: TaskboardServer,
    harness_engines,
) -> None:
    static_workspace = replay_workspace
    static_ids = await submit_case_run(
        harness_engines,
        principal_id=static_workspace.user_id,
        workspace_id=static_workspace.workspace_id,
        case=compiled_baseline("create_item_baseline.yaml"),
        environment_content=environment(taskboard_server, "coverage-static", {"item_name": ITEM_NAME}),
    )
    static_summaries = await static_workspace.harness.worker.run_until_idle()
    assert static_summaries[0].status == "succeeded", static_summaries[0]
    assert static_summaries[0].verdict == "passed", static_summaries[0]

    agent_workspace = await agent_workspace_factory(success_plan())
    agent_ids = await submit_case_run(
        harness_engines,
        principal_id=agent_workspace.user_id,
        workspace_id=agent_workspace.workspace_id,
        case=compile_case_document((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8")).case,
        environment_content=environment(taskboard_server, "coverage-agent", {"item_name": ITEM_NAME}),
        policy="llm",
    )
    agent_summaries = await agent_workspace.harness.worker.run_until_idle()
    assert agent_summaries[0].verdict == "passed", agent_summaries[0]

    static_phases, static_wall, static_aggregate = await usage_snapshot(
        harness_engines, static_workspace, static_ids["run_id"]
    )
    agent_phases, agent_wall, agent_aggregate = await usage_snapshot(
        harness_engines, agent_workspace, agent_ids["run_id"]
    )

    assert static_phases == {}, "static replay không được tự sinh model calls"
    assert static_aggregate.state == "complete"
    assert static_aggregate.unknown_calls == 0
    assert agent_phases, "agent run phải có model call telemetry"
    for bucket in agent_phases.values():
        assert set(bucket) == USAGE_BUCKET_KEYS
    assert set(static_wall) == set(agent_wall) == WALL_TIME_KEYS
    assert set(agent_wall) == WALL_TIME_KEYS
    assert agent_aggregate.state in {"complete", "partial", "unknown"}
    assert agent_aggregate.unknown_calls >= 0


@pytest.mark.asyncio
async def test_canvasdesk_visual_case_runs_end_to_end_with_baseline(
    harness_engines, test_db, taskboard_server: TaskboardServer, canvasdesk_server: CanvasdeskServer
) -> None:
    user_id, workspace_id = await seed_replay_workspace(harness_engines)
    endpoints = [f"canvasdesk@1|{canvasdesk_server.base_url}|{canvasdesk_server.control_token}"]
    baseline_dir = str(REPO_ROOT / "benchmarks" / "public" / "baselines" / "visual")
    canvas_parts = urlsplit(canvasdesk_server.base_url)
    harness = build_replay_harness(
        engines=harness_engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
        fixture_endpoints=endpoints,
        baseline_dir=baseline_dir,
        extra_allow_origins=[f"127.0.0.1:{canvas_parts.port}"],
    )
    try:
        namespace = "visual-e2e"
        case = compile_case_document(
            (REPO_ROOT / "benchmarks" / "public" / "cases" / "canvasdesk" / "theme_visual.yaml").read_text(
                encoding="utf-8"
            )
        ).case
        ids = await submit_case_run(
            harness_engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            case=case,
            environment_content={
                "target_base_url": f"{canvasdesk_server.base_url}/{namespace}",
                "fixture_ref": "canvasdesk@1",
                "namespace": namespace,
                "parameters": {},
            },
        )
        summaries = await harness.worker.run_until_idle()
        read_model = RunReadModel(harness_engines[ROLE_API])
        state = await read_model.run_state(workspace_id=workspace_id, principal_id=user_id, run_id=ids["run_id"])
        detail = await read_model.run_detail(workspace_id=workspace_id, principal_id=user_id, run_id=ids["run_id"])
        assert detail is not None
        results = {
            item["assertion_id"]: (item["result"], item["proof"])
            for execution in detail["executions"]
            for item in execution["assertions"]
        }
        compact = {key: (value[0], value[1].get("reason"), value[1].get("observed")) for key, value in results.items()}
        assert summaries[0].status == "succeeded", (summaries[0], state and state["reasons"], compact)
        assert summaries[0].verdict == "passed", (summaries[0], state and state["reasons"], compact)
        assert results.get("light_baseline", ("",))[0] == "passed"
        assert results.get("dark_baseline", ("",))[0] == "passed"
        assert results.get("dark_theme_attr", ("",))[0] == "passed"
    finally:
        harness.aclose()
