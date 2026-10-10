from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.platform.runs.read_models import RunReadModel
from tests.integration.conftest import ReplayWorkspace
from tests.support.replay import submit_case_run
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"
ITEM_NAME = "Việc nâng cao E2E"


def environment(taskboard_server: TaskboardServer, namespace: str, parameters: dict[str, str]) -> dict:
    return {
        "target_base_url": f"{taskboard_server.base_url}/{namespace}",
        "fixture_ref": "taskboard@1",
        "namespace": namespace,
        "parameters": parameters,
    }


def login_and_create_nodes() -> list[dict]:
    base = compile_case_document((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8")).case
    return [node.model_dump(mode="json") for node in base.nodes[:6]]


def scope(item_name: str = ITEM_NAME) -> dict:
    return {
        "field": "text",
        "value": {"kind": "parameter", "name": "item_name", "type": "string"},
    }


def row_target(intent: str = "created_item_row") -> dict:
    return {"intent": intent, "role": "listitem", "entity_scope": scope()}


def count_capture(capture_id: str, output: str, expected: int) -> dict:
    return {
        "kind": "capture",
        "id": capture_id,
        "probe": {
            "kind": "comparison",
            "comparator": "count_equals",
            "target": row_target(),
            "expected": {"kind": "literal", "value": expected},
        },
        "output": {"name": output, "type": "integer", "taint": "internal"},
    }


def branch_case() -> CaseContent:
    document = {
        "schema_version": "case/1",
        "logical_key": "advanced_branch_case",
        "title": "Nhánh và vòng lặp",
        "goal": "Đi qua nhánh dựa trên capture và lặp có bound",
        "requirements": [],
        "source_defs": {},
        "postcondition_defs": {},
        "parameter_defs": {"item_name": {"type": "string", "required": True}},
        "fixture_refs": ["taskboard@1"],
        "preconditions": [],
        "nodes": [
            *login_and_create_nodes(),
            {
                "kind": "action",
                "id": "wait_row",
                "operation": "wait",
                "target": row_target(),
                "side_effect": "read",
            },
            count_capture("count_rows", "rows", 1),
            {
                "kind": "branch",
                "id": "check_branch",
                "condition": {"kind": "capture", "name": "rows"},
                "then_nodes": [
                    {
                        "kind": "checkpoint",
                        "id": "result",
                        "assertions": [
                            {
                                "id": "item_exists_once",
                                "required": True,
                                "target": row_target(),
                                "comparator": "count_equals",
                                "expected": {"kind": "literal", "value": 1},
                            }
                        ],
                    }
                ],
                "else_nodes": [
                    {
                        "kind": "checkpoint",
                        "id": "else_result",
                        "assertions": [
                            {
                                "id": "else_item_absent",
                                "required": False,
                                "target": row_target(),
                                "comparator": "count_equals",
                                "expected": {"kind": "literal", "value": 0},
                            }
                        ],
                    }
                ],
            },
            {
                "kind": "loop",
                "id": "refresh_rows",
                "condition": {"kind": "capture", "name": "rows"},
                "max_iterations": 2,
                "body": [count_capture("recount", "rows", 1)],
            },
        ],
        "completion": {
            "required_nodes": ["add_item", "check_branch", "refresh_rows", "result"],
            "required_assertions": ["item_exists_once"],
        },
        "required_capabilities": [],
    }
    return CaseContent.model_validate(document)


def branch_not_taken_case() -> CaseContent:
    document = {
        "schema_version": "case/1",
        "logical_key": "advanced_branch_not_taken",
        "title": "Nhánh không được chọn với proof",
        "goal": "Required assertion trong nhánh không chọn là not applicable, không phải skipped",
        "requirements": [],
        "source_defs": {},
        "postcondition_defs": {},
        "parameter_defs": {"item_name": {"type": "string", "required": True}},
        "fixture_refs": ["taskboard@1"],
        "preconditions": [],
        "nodes": [
            *login_and_create_nodes(),
            {
                "kind": "capture",
                "id": "count_missing",
                "probe": {
                    "kind": "comparison",
                    "comparator": "count_equals",
                    "target": {
                        "intent": "missing_row",
                        "role": "listitem",
                        "entity_scope": {"field": "text", "value": {"kind": "literal", "value": "Không tồn tại"}},
                    },
                    "expected": {"kind": "literal", "value": 1},
                },
                "output": {"name": "missing_present", "type": "boolean", "taint": "internal"},
            },
            {
                "kind": "branch",
                "id": "check_missing",
                "condition": {"kind": "capture", "name": "missing_present"},
                "then_nodes": [
                    {
                        "kind": "checkpoint",
                        "id": "then_result",
                        "assertions": [
                            {
                                "id": "then_missing_exists",
                                "required": True,
                                "target": {
                                    "intent": "missing_row",
                                    "role": "listitem",
                                    "entity_scope": {
                                        "field": "text",
                                        "value": {"kind": "literal", "value": "Không tồn tại"},
                                    },
                                },
                                "comparator": "count_equals",
                                "expected": {"kind": "literal", "value": 1},
                            }
                        ],
                    }
                ],
                "else_nodes": [
                    {
                        "kind": "checkpoint",
                        "id": "else_result",
                        "assertions": [
                            {
                                "id": "created_item_present",
                                "required": True,
                                "target": row_target(),
                                "comparator": "count_equals",
                                "expected": {"kind": "literal", "value": 1},
                            }
                        ],
                    }
                ],
            },
        ],
        "completion": {
            "required_nodes": ["add_item", "check_missing", "else_result"],
            "required_assertions": ["then_missing_exists", "created_item_present"],
        },
        "required_capabilities": [],
    }
    return CaseContent.model_validate(document)


async def state_for(engines, workspace: ReplayWorkspace, run_id) -> dict:
    state = await RunReadModel(engines["agentqa_api"]).run_state(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id
    )
    assert state is not None
    return state


async def test_branch_loop_capture_runtime_with_proof(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    namespace = "advanced-branch"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=branch_case(),
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await workspace.harness.worker.run_until_idle()
    state = await state_for(harness_engines, workspace, ids["run_id"])
    detail = await RunReadModel(harness_engines["agentqa_api"]).run_detail(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"]
    )
    assert summaries[0].verdict == "passed", (
        state["reasons"],
        detail["executions"][0]["assertions"] if detail else None,
    )

    from agentqa.platform.events.service import EventService

    events = await EventService(harness_engines["agentqa_api"]).query_durable(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"], limit=500
    )
    from tests.support.replay import execution_key  # noqa: F401

    detail = await RunReadModel(harness_engines["agentqa_api"]).run_detail(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"]
    )
    assert detail is not None
    steps = detail["executions"][0]["assertions"]
    checkpoints = [event["summary"] for event in events if event["type"] == "checkpoint.evaluated"]
    assert any(step["assertion_id"] == "item_exists_once" and step["result"] == "passed" for step in steps), (
        steps,
        checkpoints,
    )
    assert events


async def test_branch_not_taken_required_assertion_is_not_applicable(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    namespace = "advanced-not-taken"
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=branch_not_taken_case(),
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "passed", await state_for(harness_engines, workspace, ids["run_id"])

    detail = await RunReadModel(harness_engines["agentqa_api"]).run_detail(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=ids["run_id"]
    )
    assert detail is not None
    assertions = detail["executions"][0]["assertions"]
    assert any(item["assertion_id"] == "created_item_present" and item["result"] == "passed" for item in assertions)
    assert all(item["assertion_id"] != "then_missing_exists" for item in assertions)


async def test_compile_receipt_marks_loop_bounds() -> None:
    document = yaml.safe_load((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
    document["nodes"].append(
        {
            "kind": "loop",
            "id": "unbounded",
            "condition": {"kind": "capture", "name": "x"},
            "max_iterations": 0,
            "body": [],
        }
    )
    case = CaseContent.model_validate(document)
    from agentqa.agent.replay.capabilities import validate_case

    report = validate_case(case)
    assert report.supported is False
    assert "unbounded" in report.unsupported_nodes
