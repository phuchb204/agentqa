from __future__ import annotations

import inspect

import pytest

from agentqa.agent.healing import AsyncHeuristicRanker, HealContext, Healer, HeuristicRanker
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.healing import HealingActor, HealingDecision, HealingRanking, RankingOutcome
from agentqa.contracts.identity import TargetDescriptor
from tests.support.healing import delete_descriptor, delete_scene, synthetic_profile


def evidence_context(node_id: str = "checkpoint:row") -> HealContext:
    return HealContext(node_id=node_id, actor=HealingActor.EVIDENCE, operation=None, scene_version=9)


class SpyRanker:
    def __init__(self, chosen: str = "c0") -> None:
        self.chosen = chosen
        self.calls: list[tuple[TargetDescriptor, list[SceneCandidate]]] = []

    async def rank(self, descriptor, scene, context):
        self.calls.append((descriptor, scene))
        return HealingRanking(
            ranker="heuristic",
            profile_id="spy",
            profile_version="1",
            outcome=RankingOutcome.RECOVER,
            scores=[{"candidate_id": self.chosen, "score": 0.9}],
            margin=None,
        )


@pytest.mark.asyncio
async def test_evidence_ranking_receives_only_descriptor_and_scene() -> None:
    spy = SpyRanker()
    healer = Healer(profile=synthetic_profile(), ranker=spy)
    descriptor = delete_descriptor("Việc A")
    scene = [delete_scene("Việc A", button_name="Xoá việc")]
    decision = await healer.recover(descriptor, scene, evidence_context())
    assert decision.recovered is True
    captured_descriptor, captured_scene = spy.calls[0]
    assert captured_descriptor == descriptor
    assert captured_scene == scene
    parameters = set(inspect.signature(Healer.recover).parameters) - {"self"}
    assert parameters == {"descriptor", "scene", "context"}
    rank_parameters = set(inspect.signature(SpyRanker.rank).parameters) - {"self"}
    assert rank_parameters == {"descriptor", "scene", "context"}


@pytest.mark.asyncio
async def test_evidence_recovery_preserves_intent_and_entity_scope() -> None:
    healer = Healer(profile=synthetic_profile(), ranker=AsyncHeuristicRanker(HeuristicRanker(synthetic_profile())))
    descriptor = delete_descriptor("Việc A")
    scene = [delete_scene("Việc A", button_name="Xoá việc", attributes={"data-testid": "delete-a"})]
    decision = await healer.recover(descriptor, scene, evidence_context())
    assert decision.recovered is True
    target = decision.recovered_target
    assert target is not None
    assert target.intent == "delete_item"
    assert target.entity_scope == descriptor.entity_scope
    assert set(target.model_dump(mode="json")) == set(descriptor.model_dump(mode="json"))
    assert decision.record.actor == HealingActor.EVIDENCE
    assert decision.record.proposal is not None


@pytest.mark.asyncio
async def test_ranker_pick_on_wrong_entity_is_rejected_at_admission() -> None:
    spy = SpyRanker(chosen="c0")
    healer = Healer(profile=synthetic_profile(), ranker=spy)
    descriptor = delete_descriptor("Việc A")
    wrong_row = [delete_scene("Việc B", button_name="Xoá", candidate_id="c0")]
    decision = await healer.recover(descriptor, wrong_row, evidence_context())
    assert decision.recovered is False
    assert decision.record.decision == HealingDecision.REFUSED
    assert decision.record.refusal_reason == "admission_rejected:entity_scope_mismatch"
    assert decision.recovered_target is None


@pytest.mark.asyncio
async def test_read_context_can_recover_hidden_evidence_but_stateful_action_cannot() -> None:
    hidden = SceneCandidate(candidate_id="c0", role="listitem", name="Việc A", visible=False, entity_text="Việc A")
    descriptor = TargetDescriptor(intent="created_item_row", role="listitem", name="Việc A")
    read_healer = Healer(profile=synthetic_profile(), ranker=AsyncHeuristicRanker(HeuristicRanker(synthetic_profile())))
    evidence = await read_healer.recover(descriptor, [hidden], evidence_context())
    assert evidence.recovered is True

    action_context = HealContext(node_id="n1", actor=HealingActor.ACTION, operation=Operation.CLICK)
    action = await read_healer.recover(descriptor, [hidden], action_context)
    assert action.recovered is False
    assert action.record.refusal_reason == "no_candidate"


@pytest.mark.asyncio
async def test_evidence_recovery_requires_scene_and_never_invents_evidence() -> None:
    healer = Healer(profile=synthetic_profile(), ranker=AsyncHeuristicRanker(HeuristicRanker(synthetic_profile())))
    descriptor = delete_descriptor("Việc A")
    decision = await healer.recover(descriptor, [], evidence_context())
    assert decision.recovered is False
    assert decision.record.refusal_reason == "no_candidate"
    assert decision.record.ranking is not None
    assert decision.record.ranking.outcome == RankingOutcome.NONE
    assert decision.record.actual_target is None
