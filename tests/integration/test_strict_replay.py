from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.runs import ControlAction
from agentqa.platform.events.service import EventService
from agentqa.platform.recovery import RecoveryService
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.runs.service import RunService
from agentqa.platform.storage.database import create_session_factory
from tests.integration.conftest import ReplayWorkspace
from tests.support.replay import submit_case_run
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"
ITEM_NAME = "Việc E2E"


def compiled_case(name: str) -> CaseContent:
    return compile_case_document((CASE_DIR / name).read_text(encoding="utf-8")).case


def environment(taskboard_server: TaskboardServer | None, namespace: str, parameters: dict[str, str]) -> dict:
    base = taskboard_server.base_url if taskboard_server is not None else "http://127.0.0.1:1"
    return {
        "target_base_url": f"{base}/{namespace}",
        "fixture_ref": "taskboard@1",
        "namespace": namespace,
        "parameters": parameters,
    }


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


async def run_state(engines, workspace: ReplayWorkspace, run_id) -> dict | None:
    return await RunReadModel(engines["agentqa_api"]).run_state(
        workspace_id=workspace.workspace_id, principal_id=workspace.user_id, run_id=run_id
    )


async def test_end_to_end_strict_replay_passed_with_trace(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    harness = workspace.harness
    namespace = "e2e-pass"
    case = compiled_case("login_create_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await harness.worker.run_until_idle()
    state = await run_state(harness_engines, workspace, ids["run_id"])
    assert len(summaries) == 1
    assert summaries[0].status == "succeeded", state
    assert summaries[0].verdict == "passed", state

    assert state is not None
    assert state["status"] == "succeeded"
    assert state["verdict"] == "passed"
    assert state["executions"][0]["verdict"] == "passed"

    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe["label_counts"][ITEM_NAME] == 1
    assert probe["counters"].get("item_created") == 1
    event_types = {event["type"] for event in events}
    assert {"run.state_changed", "checkpoint.evaluated", "run.finalized", "fixture.probed"} <= event_types
    assert any(event["execution_seq"] is not None for event in events)

    receipts = await harness.journal.receipts(ids["attempt_id"])
    states = [receipt.state for receipt in receipts]
    assert states.count("settled") >= 5
    assert "accepted" in states and "dispatched" in states

    from uuid import uuid4

    from agentqa.platform.runs.service import SubmitRequest

    resubmit = await RunService(harness_engines["agentqa_api"]).submit(
        SubmitRequest(
            workspace_id=workspace.workspace_id,
            principal_id=workspace.user_id,
            actor="tester",
            idempotency_key=uuid4().hex,
            case_revision_ids=(ids["case_revision_id"],),
            environment_revision_id=ids["environment_revision_id"],
            provided_capabilities=frozenset(),
        )
    )
    assert resubmit.snapshot_digest == ids["snapshot_digest"]


async def test_missing_required_assertion_is_inconclusive_but_action_ran(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    harness = workspace.harness
    namespace = "e2e-missing-assertion"
    document = yaml.safe_load((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
    document["nodes"][-1]["assertions"][0]["required"] = False
    document["completion"]["required_assertions"] = []
    case = CaseContent.model_validate(document)
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await harness.worker.run_until_idle()
    assert summaries[0].verdict == "inconclusive"
    state = await run_state(harness_engines, workspace, ids["run_id"])
    assert state is not None and state["verdict"] == "inconclusive"
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert probe_from_events(events)["label_counts"][ITEM_NAME] == 1


async def test_capability_validator_rejects_unsupported_node_without_actions(
    replay_workspace: ReplayWorkspace, harness_engines
) -> None:
    workspace = replay_workspace
    harness = workspace.harness
    case = CaseContent.model_validate(
        {
            "schema_version": "case/1",
            "logical_key": "unsupported_capture",
            "title": "Unsupported",
            "goal": "Gate capability",
            "requirements": ["r1"],
            "nodes": [
                {
                    "id": "capture-flag",
                    "kind": "capture",
                    "probe": {
                        "kind": "comparison",
                        "comparator": "exists",
                        "target": {"intent": "flag"},
                    },
                    "output": {"name": "flag", "type": "boolean"},
                }
            ],
            "completion": {"required_nodes": ["capture-flag"], "required_assertions": []},
        }
    )
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(None, "e2e-capability", {}),
    )
    summaries = await harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"
    assert await harness.journal.receipts(ids["attempt_id"]) == []
    state = await run_state(harness_engines, workspace, ids["run_id"])
    assert state is not None and state["verdict"] == "inconclusive"


async def test_unknown_side_effect_is_not_replayed_and_requires_fixture_reset(
    loss_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = loss_workspace
    harness = workspace.harness
    namespace = "e2e-unknown"
    case = compiled_case("login_create_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await harness.worker.run_until_idle()
    assert summaries[0].status == "error"
    assert summaries[0].verdict == "inconclusive"

    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    probe = probe_from_events(events)
    assert probe["label_counts"].get(ITEM_NAME, 0) == 1

    receipts = await harness.journal.receipts(ids["attempt_id"])
    assert receipts[-1].state == "unknown"

    recovery = RecoveryService(
        create_session_factory(harness_engines["agentqa_supervisor"]),
        harness.journal,
        workspace_id=workspace.workspace_id,
        principal_id=workspace.user_id,
    )
    blocked = await recovery.retry_decision(ids["attempt_id"], fixture_reset_ok=False)
    assert blocked.allowed is False
    allowed = await recovery.retry_decision(ids["attempt_id"], fixture_reset_ok=True)
    assert allowed.allowed is True


async def test_storage_fault_yields_inconclusive_not_false_pass(
    storage_fault_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = storage_fault_workspace
    harness = workspace.harness
    namespace = "e2e-storage-fault"
    case = compiled_case("login_create_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    summaries = await harness.worker.run_until_idle()
    assert summaries[0].verdict == "inconclusive"
    state = await run_state(harness_engines, workspace, ids["run_id"])
    assert state is not None and state["verdict"] == "inconclusive"
    assert "verification_errors" in state["reasons"]
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert probe_from_events(events)["label_counts"][ITEM_NAME] == 1


async def test_pause_control_becomes_effective_and_blocks_dispatch(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    harness = workspace.harness
    namespace = "e2e-pause"
    case = compiled_case("login_create_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        case=case,
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    run_service = RunService(harness_engines["agentqa_api"])
    control = await run_service.request_control(
        workspace_id=workspace.workspace_id,
        principal_id=workspace.user_id,
        actor="tester",
        run_id=ids["run_id"],
        action=ControlAction.PAUSE,
    )
    summaries = await harness.worker.run_until_idle()
    assert summaries[0].verdict == "inconclusive"

    state = await run_state(harness_engines, workspace, ids["run_id"])
    assert state is not None
    assert state["controls"][0]["control_id"] == control.control_id
    assert state["controls"][0]["effective_at"] is not None
    events = await recorded_events(harness_engines, workspace, ids["run_id"])
    assert probe_from_events(events).get("item_count", 0) == 0


async def test_multi_execution_run_seq_cursor_no_gap_or_duplicate(
    replay_workspace: ReplayWorkspace, taskboard_server: TaskboardServer, harness_engines
) -> None:
    workspace = replay_workspace
    harness = workspace.harness
    namespace = "e2e-multi"
    case = compiled_case("login_create_item.yaml")
    ids = await submit_case_run(
        harness_engines,
        principal_id=workspace.user_id,
        workspace_id=workspace.workspace_id,
        cases=(case, case),
        environment_content=environment(taskboard_server, namespace, {"item_name": ITEM_NAME}),
    )
    assert len(ids["execution_ids"]) == 2
    summaries = await harness.worker.run_until_idle()
    assert len(summaries) == 2
    assert all(summary.verdict == "passed" for summary in summaries)

    events = EventService(harness_engines["agentqa_api"])
    full = await events.query_durable(
        workspace_id=workspace.workspace_id,
        principal_id=workspace.user_id,
        run_id=ids["run_id"],
        limit=500,
    )
    sequences = [event["run_seq"] for event in full]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len({event["event_id"] for event in full}) == len(full)

    paged: list[dict] = []
    cursor = 0
    while True:
        page = await events.query_durable(
            workspace_id=workspace.workspace_id,
            principal_id=workspace.user_id,
            run_id=ids["run_id"],
            after_run_seq=cursor,
            limit=1,
        )
        if not page:
            break
        paged.extend(page)
        cursor = page[-1]["run_seq"]
        await asyncio.sleep(0)
    assert [event["event_id"] for event in paged] == [event["event_id"] for event in full]
