from __future__ import annotations

from pathlib import Path

import pytest

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.platform.events.service import EventService
from agentqa.platform.runs.read_models import RunReadModel
from tests.integration.conftest import ReplayWorkspace
from tests.support.replay import submit_case_run
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"
ITEM_NAME = "Việc Agent E2E"

LOGIN_USERNAME = {"role": "textbox", "name": "Tài khoản"}
LOGIN_PASSWORD = {"role": "textbox", "name": "Mật khẩu"}
LOGIN_SUBMIT = {"role": "button", "name": "Đăng nhập"}
NEW_ITEM = {"role": "textbox", "name": "Việc mới"}
CREATE_ITEM = {"role": "button", "name": "Thêm việc"}


def compiled_case(name: str) -> CaseContent:
    return compile_case_document((CASE_DIR / name).read_text(encoding="utf-8")).case


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
            {
                "operation": "navigate",
                "intent": "open_login",
                "value": {"kind": "literal", "value": "/login"},
            },
            {"operation": "fill", "intent": "login_username", "match": LOGIN_USERNAME},
            {"operation": "fill", "intent": "login_password", "match": LOGIN_PASSWORD},
            {"operation": "click", "intent": "login_submit", "match": LOGIN_SUBMIT},
            {"operation": "fill", "intent": "new_item", "match": NEW_ITEM},
            {"operation": "click", "intent": "create_item", "match": CREATE_ITEM},
            {"raw": {"decision": "stop", "rationale": "script complete"}},
        ]
    }


def custom_action_case(node_id: str, intent: str, name: str) -> CaseContent:
    return CaseContent.model_validate(
        {
            "schema_version": "case/1",
            "logical_key": f"agent_{node_id}",
            "title": "Agent action case",
            "goal": f"Thực hiện {intent}",
            "requirements": ["req-agent"],
            "nodes": [
                {
                    "id": node_id,
                    "kind": "action",
                    "operation": "click",
                    "target": {"intent": intent, "role": "button", "name": name},
                    "side_effect": "reversible",
                }
            ],
            "completion": {"required_nodes": [node_id], "required_assertions": []},
        }
    )


async def recorded_events(engines, workspace: ReplayWorkspace, run_id) -> list[dict]:
    events = EventService(engines["agentqa_api"])
    return await events.query_durable(
        workspace_id=workspace.workspace_id,
        principal_id=workspace.user_id,
        run_id=run_id,
        limit=500,
    )


def probe_from_events(events: list[dict]) -> dict:
    for event in reversed(events):
        if event["type"] == "fixture.probed":
            return event["summary"].get("probe", {})
    return {}


async def test_agent_llm_success_flow_with_real_browser_and_fake_models(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = await agent_workspace_factory(success_plan())
    namespace = "agent-pass"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=compiled_case("login_create_item.yaml"),
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert len(summaries) == 1
    assert summaries[0].status == "succeeded", summaries[0]
    assert summaries[0].verdict == "passed", summaries[0]

    probe = probe_from_events(events)
    assert probe["label_counts"][ITEM_NAME] == 1
    assert probe["counters"].get("item_created") == 1
    event_types = {event["type"] for event in events}
    assert {"checkpoint.evaluated", "run.finalized", "fixture.probed"} <= event_types
    settled = [event for event in events if event["type"] == "action.settled"]
    assert len(settled) >= 6


async def test_agent_business_failure_keeps_verify_authority(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    plan = success_plan()
    plan["go"] = [*plan["go"][:4], {"raw": {"decision": "stop", "rationale": "dừng trước khi tạo việc"}}]
    workspace = await agent_workspace_factory(plan)
    namespace = "agent-business-fail"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=compiled_case("login_create_item.yaml"),
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "failed", summaries[0]
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe["label_counts"].get(ITEM_NAME, 0) == 0


async def test_agent_stuck_flow_is_inconclusive_not_passed(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    plan = {
        "go": [
            {"operation": "click", "intent": "create_item", "match": LOGIN_SUBMIT},
            {"operation": "click", "intent": "create_item", "match": LOGIN_SUBMIT},
            {"operation": "click", "intent": "create_item", "match": LOGIN_SUBMIT},
            {"raw": {"decision": "stop", "rationale": "unreachable"}},
        ]
    }
    workspace = await agent_workspace_factory(plan)
    namespace = "agent-stuck"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=custom_action_case("create_item", "create_item", "Thêm việc"),
        environment_content=environment(taskboard_server, namespace, {}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe["counters"].get("item_created") is None


async def test_agent_low_confidence_never_acts(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    plan = {"go": [{"operation": "click", "intent": "create_item", "match": LOGIN_SUBMIT, "confidence": 0.2}]}
    workspace = await agent_workspace_factory(plan)
    namespace = "agent-low-confidence"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=custom_action_case("create_item", "create_item", "Thêm việc"),
        environment_content=environment(taskboard_server, namespace, {}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "inconclusive"
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert not [event for event in events if event["type"] == "action.settled"]


async def test_agent_malformed_output_is_typed_and_inconclusive(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    plan = {
        "go": [
            {"raw": {"decision": "explode"}},
            {"raw": {"decision": "explode"}},
        ]
    }
    workspace = await agent_workspace_factory(plan)
    namespace = "agent-malformed"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=custom_action_case("create_item", "create_item", "Thêm việc"),
        environment_content=environment(taskboard_server, namespace, {}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert not [event for event in events if event["type"] == "action.settled"]


async def test_agent_provider_loss_is_inconclusive_without_route_change(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    plan = {"go": [{"error": "provider_quota"}]}
    workspace = await agent_workspace_factory(plan)
    namespace = "agent-provider-loss"
    await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=custom_action_case("create_item", "create_item", "Thêm việc"),
        environment_content=environment(taskboard_server, namespace, {}),
        policy="llm",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"


async def test_agent_matrix_rejects_cascade_with_vision_first(
    agent_workspace_factory, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = await agent_workspace_factory({"go": []})
    namespace = "agent-matrix"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=custom_action_case("create_item", "create_item", "Thêm việc"),
        environment_content=environment(taskboard_server, namespace, {}),
        policy="jev_cascade",
        observation_mode="vision_first",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert not [event for event in events if event["type"] == "action.settled"]
    state = await RunReadModel(harness_engines["agentqa_api"]).run_state(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"]
    )
    assert state is not None
    assert "policy_config_invalid" in state["reasons"]
