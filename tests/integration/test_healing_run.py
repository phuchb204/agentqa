from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.platform.events.service import EventService
from agentqa.platform.fixtures.taskboard import synthetic_password
from agentqa.platform.healing import HealingService
from agentqa.platform.runs.read_models import RunReadModel
from tests.integration.conftest import ReplayWorkspace
from tests.support.replay import submit_case_run
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"
ITEM_NAME = "Việc healing E2E"


def compiled_case(name: str) -> CaseContent:
    return compile_case_document((CASE_DIR / name).read_text(encoding="utf-8")).case


def environment(taskboard_server: TaskboardServer, namespace: str, parameters: dict[str, str]) -> dict:
    return {
        "target_base_url": f"{taskboard_server.base_url}/{namespace}",
        "fixture_ref": "taskboard@1",
        "namespace": namespace,
        "parameters": parameters,
    }


async def healing_records(engines, workspace: ReplayWorkspace, run_id) -> list[dict]:
    records = await HealingService(engines["agentqa_api"]).list_for_run(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id
    )
    assert records is not None
    return records


async def events_for(engines, workspace: ReplayWorkspace, run_id) -> list[dict]:
    return await EventService(engines["agentqa_api"]).query_durable(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id, limit=500
    )


def probe_from_events(events: list[dict]) -> dict:
    for event in reversed(events):
        if event["type"] == "fixture.probed":
            return event["summary"].get("probe", {})
    return {}


async def state_for(engines, workspace: ReplayWorkspace, run_id) -> dict:
    state = await RunReadModel(engines["agentqa_api"]).run_state(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id
    )
    assert state is not None
    return state


async def detail_for(engines, workspace: ReplayWorkspace, run_id) -> dict:
    detail = await RunReadModel(engines["agentqa_api"]).run_detail(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id
    )
    assert detail is not None
    return detail


async def test_valid_heal_passes_with_allow_healing_gate(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-valid"
    case = compiled_case("healing_delete_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="allow_healing",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert summaries[0].verdict == "passed", state
    assert state["verdict"] == "passed"
    assert state["gate"] == "passed"
    assert "healed" in state["reasons"]

    records = await healing_records(harness_engines, workspace, ids["run_id"])
    action_records = [record for record in records if record["actor"] == "action"]
    assert len(action_records) == 1
    record = action_records[0]
    assert record["decision"] == "recovered"
    assert record["node_id"] == "delete_item"
    assert record["original_target"]["name"] == "Xoá việc"
    assert record["actual_target"]["name"] == "Xoá"
    assert record["guard_checks"]
    assert record["postconditions_ok"] is True
    assert record["dispatch_outcome"] == "succeeded"
    assert record["proposal"] is not None
    assert record["proposal"]["source_run_id"] == str(ids["run_id"])
    assert str(record["source_run_id"]) == str(ids["run_id"])
    assert str(record["case_id"]) == str(ids["case_id"])
    assert str(record["case_revision_id"]) == str(ids["case_revision_id"])

    events = await events_for(harness_engines, workspace, ids["run_id"])
    assert any(event["type"] == "healing.accepted" for event in events)
    probe = probe_from_events(events)
    assert probe.get("label_counts", {}).get(ITEM_NAME, 0) == 0


async def test_valid_heal_strict_gate_rejects_without_business_failure(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-strict"
    case = compiled_case("healing_delete_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="strict",
    )
    await workspace.harness.worker.run_until_idle()
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["verdict"] == "passed"
    assert state["gate"] == "refused"
    assert "healed" in state["reasons"]
    assert "business_failure" not in state["reasons"]
    detail = await detail_for(harness_engines, workspace, ids["run_id"])
    assert "healed" in detail["annotations"]
    assert detail["snapshot"]["gate_profile"] == "strict"

    records = await healing_records(harness_engines, workspace, ids["run_id"])
    assert [record["decision"] for record in records] == ["recovered"]


async def test_ambiguous_duplicates_are_refused_and_nothing_deleted(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-ambiguous"
    document = yaml.safe_load((CASE_DIR / "healing_delete_item.yaml").read_text(encoding="utf-8"))
    document["logical_key"] = "taskboard_delete_ambiguous"
    add_node = next(node for node in document["nodes"] if node["id"] == "add_item")
    fill_node = next(node for node in document["nodes"] if node["id"] == "item_name")
    insert_at = document["nodes"].index(add_node) + 1
    document["nodes"].insert(insert_at, dict(fill_node, id="item_name_again"))
    document["nodes"].insert(insert_at + 1, dict(add_node, id="add_item_again"))
    delete_node = next(node for node in document["nodes"] if node["id"] == "delete_item")
    delete_node["target"] = {"intent": "delete_item", "role": "button", "name": "Xoá"}
    delete_node["postconditions"] = []
    case = CaseContent.model_validate(document)
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="allow_healing",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "inconclusive"
    records = await healing_records(harness_engines, workspace, ids["run_id"])
    refusals = [record for record in records if record["decision"] == "refused"]
    assert refusals
    assert refusals[0]["refusal_reason"] == "ambiguous_margin"
    assert len(refusals[0]["ranking"]["scores"]) >= 2
    events = await events_for(harness_engines, workspace, ids["run_id"])
    assert any(event["type"] == "healing.refused" for event in events)
    probe = probe_from_events(events)
    assert probe["label_counts"].get(ITEM_NAME) == 2
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["verdict"] == "inconclusive"
    assert state["gate"] == "refused"


async def test_wrong_entity_scope_is_refused_without_click(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-wrong-entity"
    document = yaml.safe_load((CASE_DIR / "healing_delete_item.yaml").read_text(encoding="utf-8"))
    document["logical_key"] = "taskboard_delete_wrong_entity"
    delete_node = next(node for node in document["nodes"] if node["id"] == "delete_item")
    delete_node["target"] = {
        "intent": "delete_item",
        "role": "button",
        "name": "Xoá",
        "entity_scope": {"field": "text", "value": {"kind": "literal", "value": "Việc không tồn tại"}},
    }
    case = CaseContent.model_validate(document)
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="allow_healing",
    )
    await workspace.harness.worker.run_until_idle()
    records = await healing_records(harness_engines, workspace, ids["run_id"])
    refusals = [record for record in records if record["decision"] == "refused"]
    assert refusals
    assert refusals[0]["refusal_reason"] == "admission_rejected:entity_scope_mismatch"
    events = await events_for(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe["label_counts"].get(ITEM_NAME) == 1
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["verdict"] == "inconclusive"


async def test_healed_but_failed_final_keeps_business_failure(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-failed-final"
    document = yaml.safe_load((CASE_DIR / "healing_delete_item.yaml").read_text(encoding="utf-8"))
    document["logical_key"] = "taskboard_delete_expect_still_there"
    assertion = document["nodes"][-1]["assertions"][0]
    assertion["expected"] = {"kind": "literal", "value": 1}
    case = CaseContent.model_validate(document)
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="allow_healing",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "failed"
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["verdict"] == "failed"
    assert any(reason.startswith("failed_assertion:") for reason in state["reasons"])
    records = await healing_records(harness_engines, workspace, ids["run_id"])
    action_records = [record for record in records if record["actor"] == "action"]
    assert action_records and action_records[0]["decision"] == "recovered"
    events = await events_for(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe.get("label_counts", {}).get(ITEM_NAME, 0) == 0


async def test_evidence_locator_repair_records_evidence_actor_and_secret_stays_hidden(
    healing_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = healing_workspace
    namespace = "heal-evidence"
    case = compiled_case("healing_evidence_visible.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_healing",
        gate_profile="allow_healing",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "passed"
    records = await healing_records(harness_engines, workspace, ids["run_id"])
    evidence_records = [record for record in records if record["actor"] == "evidence"]
    assert len(evidence_records) == 1
    record = evidence_records[0]
    assert record["decision"] == "recovered"
    assert record["node_id"] == "result:delete_button_visible"
    assert record["original_target"]["name"] == "Xoá cũ"
    assert record["actual_target"]["name"] == "Xoá"
    assert record["guard_checks"]

    events = await events_for(harness_engines, workspace, ids["run_id"])
    canary = synthetic_password(namespace, "alice")
    payload = json.dumps(records, ensure_ascii=False, default=str) + json.dumps(events, ensure_ascii=False, default=str)
    assert canary not in payload
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["verdict"] == "passed"


async def test_strict_replay_without_healer_fails_same_drifted_evidence(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    namespace = "strict-evidence"
    case = compiled_case("healing_evidence_visible.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
        policy="replay_strict",
        gate_profile="allow_healing",
    )
    summaries = await workspace.harness.worker.run_until_idle()
    assert summaries[0].verdict == "failed"
    records = await healing_records(harness_engines, workspace, ids["run_id"])
    assert records == []
    state = await state_for(harness_engines, workspace, ids["run_id"])
    assert state["gate"] == "refused"
    assert any(reason.startswith("failed_assertion:") for reason in state["reasons"])
