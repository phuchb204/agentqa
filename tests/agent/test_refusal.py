from __future__ import annotations

from uuid import uuid4

import pytest

from agentqa.agent.healing import Healer
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.agent.replay.runner import ActionOutcomeView, ReplayRunner
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import CaseContent
from agentqa.contracts.healing import HealingActor, HealingDecision
from agentqa.contracts.identity import TargetDescriptor
from tests.support.healing import delete_descriptor, delete_scene, synthetic_profile


def action_node(target: dict, *, postconditions: list[str] | None = None) -> dict:
    return {
        "kind": "action",
        "id": "delete_item",
        "operation": "click",
        "target": target,
        "side_effect": "external_write",
        "postconditions": postconditions or [],
    }


def case_with(nodes: list[dict], postcondition_defs: dict | None = None) -> CaseContent:
    document = {
        "schema_version": "case/1",
        "logical_key": "healing_case",
        "title": "Healing case",
        "goal": "Xoá việc đúng hàng",
        "requirements": [],
        "source_defs": {},
        "postcondition_defs": postcondition_defs or {},
        "parameter_defs": {},
        "fixture_refs": [],
        "preconditions": [],
        "nodes": nodes,
        "completion": {"required_nodes": [node["id"] for node in nodes], "required_assertions": []},
        "required_capabilities": [],
    }
    return CaseContent.model_validate(document)


def target_document(item_name: str = "Việc A") -> dict:
    return delete_descriptor(item_name).model_dump(mode="json")


class FakeHooks:
    def __init__(self, scene: list[SceneCandidate], postconditions: dict[str, bool] | None = None) -> None:
        self._scene = scene
        self._postconditions = postconditions or {}
        self.dispatched: list[TargetDescriptor | None] = []
        self.healing = []
        self.traces: list[str] = []

    async def current_scene_version(self) -> int:
        return 7

    async def scene(self) -> list[SceneCandidate]:
        return self._scene

    async def dispatch_action(self, node, scene_version: int) -> ActionOutcomeView:
        self.dispatched.append(node.target)
        return ActionOutcomeView(command_id=uuid4(), state="settled", outcome="succeeded")

    async def evaluate_checkpoint(self, node):  # pragma: no cover - không dùng trong file này
        return []

    async def evaluate_postcondition(self, node, name: str) -> bool | None:
        return self._postconditions.get(name, True)

    async def record_healing(self, record) -> None:
        self.healing.append(record)

    async def record_trace(self, label: str) -> str:
        self.traces.append(label)
        return f"mem://{label}"


class BoomRanker:
    async def rank(self, descriptor, scene, context):
        raise RuntimeError("ranker hỏng")


@pytest.mark.asyncio
async def test_no_candidate_refusal_is_recorded_and_step_aborts() -> None:
    hooks = FakeHooks([])
    case = case_with([action_node(target_document("Việc A"))])
    runner = ReplayRunner(
        case, hooks=hooks, healer=Healer(profile=synthetic_profile(), ranker=_heuristic(synthetic_profile()))
    )
    outcome = await runner.run()
    assert outcome.aborted_reason == "healing_refused:no_candidate"
    assert len(outcome.healing_records) == 1
    record = outcome.healing_records[0]
    assert record.decision == HealingDecision.REFUSED
    assert record.refusal_reason == "no_candidate"
    assert record.original_target is not None
    assert outcome.steps[-1].status == "guard_rejected"
    assert outcome.steps[-1].detail["healing"]["refusal_reason"] == "no_candidate"
    assert hooks.dispatched == []


@pytest.mark.asyncio
async def test_ambiguous_duplicates_refused_with_full_ranking() -> None:
    twins = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c1"),
    ]
    hooks = FakeHooks(twins)
    case = case_with([action_node(target_document("Việc A"))])
    runner = ReplayRunner(case, hooks=hooks, healer=_healer(synthetic_profile()))
    outcome = await runner.run()
    record = outcome.healing_records[0]
    assert record.decision == HealingDecision.REFUSED
    assert record.refusal_reason == "ambiguous_margin"
    assert record.ranking is not None
    assert len(record.ranking.scores) == 2
    assert record.ranking.margin == 0
    assert hooks.dispatched == []


@pytest.mark.asyncio
async def test_wrong_entity_recovery_rejected_before_dispatch() -> None:
    wrong_row = [delete_scene("Việc B", button_name="Xoá việc")]
    hooks = FakeHooks(wrong_row)
    case = case_with([action_node(target_document("Việc A"))])
    runner = ReplayRunner(case, hooks=hooks, healer=_healer(synthetic_profile()))
    outcome = await runner.run()
    record = outcome.healing_records[0]
    assert record.decision == HealingDecision.REFUSED
    assert record.refusal_reason == "admission_rejected:entity_scope_mismatch"
    assert hooks.dispatched == []


@pytest.mark.asyncio
async def test_postcondition_failure_is_recorded_on_healed_attempt() -> None:
    scene = [delete_scene("Việc A", button_name="Xoá việc")]
    hooks = FakeHooks(scene, postconditions={"item_deleted": False})
    node = action_node(target_document("Việc A"), postconditions=["item_deleted"])
    case = case_with([node])
    runner = ReplayRunner(case, hooks=hooks, healer=_healer(synthetic_profile()))
    outcome = await runner.run()
    assert outcome.aborted_reason == "postcondition_failed:delete_item"
    record = outcome.healing_records[-1]
    assert record.decision == HealingDecision.RECOVERED
    assert record.postconditions_ok is False
    assert record.dispatch_outcome == "succeeded"
    assert len(hooks.dispatched) == 1


@pytest.mark.asyncio
async def test_ranking_error_is_captured_as_refusal() -> None:
    hooks = FakeHooks([delete_scene("Việc A", button_name="Xoá việc")])
    case = case_with([action_node(target_document("Việc A"))])
    healer = Healer(profile=synthetic_profile(), ranker=BoomRanker())
    runner = ReplayRunner(case, hooks=hooks, healer=healer)
    outcome = await runner.run()
    record = outcome.healing_records[0]
    assert record.decision == HealingDecision.REFUSED
    assert record.refusal_reason == "ranking_error"
    assert record.error is not None and "RuntimeError" in record.error


@pytest.mark.asyncio
async def test_case_content_digest_unchanged_after_recovery() -> None:
    scene = [delete_scene("Việc A", button_name="Xoá việc")]
    hooks = FakeHooks(scene)
    case = case_with([action_node(target_document("Việc A"))])
    before = digest_content(case)
    runner = ReplayRunner(case, hooks=hooks, healer=_healer(synthetic_profile()))
    outcome = await runner.run()
    assert outcome.healing_records[0].decision == HealingDecision.RECOVERED
    assert digest_content(case) == before
    assert hooks.dispatched[0] is not None
    assert hooks.dispatched[0].name == "Xoá việc"
    assert hooks.dispatched[0].entity_scope == case.nodes[0].target.entity_scope
    assert hooks.healing[-1].actor == HealingActor.ACTION


def _heuristic(profile):
    from agentqa.agent.healing import AsyncHeuristicRanker, HeuristicRanker

    return AsyncHeuristicRanker(HeuristicRanker(profile))


@pytest.mark.asyncio
async def test_identical_twins_refused_by_identity_rule_when_margin_passes() -> None:
    profile = synthetic_profile(margin_min=0.0)
    twins = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c1"),
    ]
    hooks = FakeHooks(twins)
    case = case_with([action_node(target_document("Việc A"))])
    runner = ReplayRunner(case, hooks=hooks, healer=_healer(profile))
    outcome = await runner.run()
    record = outcome.healing_records[0]
    assert record.decision == HealingDecision.REFUSED
    assert record.refusal_reason == "duplicate_identity"
    assert len(record.ranking.scores) == 2
    assert hooks.dispatched == []


def _healer(profile) -> Healer:
    return Healer(profile=profile, ranker=_heuristic(profile))
