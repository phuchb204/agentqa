from __future__ import annotations

import pytest

from agentqa.agent.healing import HealContext, HeuristicRanker, build_healer, build_ranker, build_runtime_target
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.contracts.healing import HealingActor, HealingDecision
from agentqa.contracts.identity import LocatorKind
from agentqa.contracts.models import ChoiceAnswer
from agentqa.models.fakes import FakeJev, ScriptedJevReply
from tests.support.healing import delete_descriptor, delete_scene, synthetic_profile


def context(node_id: str = "delete_item", operation: Operation | None = Operation.CLICK) -> HealContext:
    return HealContext(node_id=node_id, actor=HealingActor.ACTION, operation=operation, scene_version=4)


@pytest.mark.asyncio
async def test_recover_valid_target_records_proof_and_runtime_binding() -> None:
    healer = build_healer(synthetic_profile())
    descriptor = delete_descriptor("Việc A")
    scene = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0", attributes={"data-testid": "delete-a"}),
    ]
    decision = await healer.recover(descriptor, scene, context())
    assert decision.recovered is True
    record = decision.record
    assert record.decision == HealingDecision.RECOVERED
    assert record.actor == HealingActor.ACTION
    assert record.opportunity_id.startswith("opp-")
    assert record.attempt_id.startswith("heal-")
    assert record.actual_signature == scene[0].stable_signature()
    assert record.guard_checks
    assert record.original_target == descriptor
    assert record.proposal is not None
    assert record.proposal.proposed.locators[0].kind == LocatorKind.TEST_ID
    assert decision.recovered_target is not None
    assert decision.recovered_target.intent == descriptor.intent
    assert decision.recovered_target.entity_scope == descriptor.entity_scope
    assert decision.recovered_target.attributes == {}


@pytest.mark.asyncio
async def test_healer_refuses_duplicates_for_ranker_without_own_check() -> None:
    from agentqa.agent.healing import Healer
    from agentqa.contracts.healing import HealingCandidateScore, HealingRanking, RankingOutcome

    class AlwaysRecover:
        async def rank(self, descriptor, scene, context):
            return HealingRanking(
                ranker=RankerKind.LLM,
                profile_id="synthetic",
                profile_version="1",
                outcome=RankingOutcome.RECOVER,
                scores=[HealingCandidateScore(candidate_id=item.candidate_id, score=0.9) for item in scene],
                margin=0.1,
                truncated=False,
                total_candidates=len(scene),
                reason=None,
            )

    healer = Healer(profile=synthetic_profile(), ranker=AlwaysRecover())
    descriptor = delete_descriptor("Việc A")
    twins = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c1"),
    ]
    decision = await healer.recover(descriptor, twins, context())
    assert decision.recovered is False
    assert decision.record.refusal_reason == "duplicate_identity"
    assert decision.recovered_target is None

    distinct = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Đổi trạng thái", candidate_id="c1"),
    ]
    decision = await healer.recover(descriptor, distinct, context())
    assert decision.recovered is True
    assert decision.recovered_target is not None


@pytest.mark.asyncio
async def test_recovery_refuses_semantic_drift_even_when_score_is_high() -> None:
    healer = build_healer(synthetic_profile())
    descriptor = delete_descriptor("Việc A")
    drifted = [delete_scene("Việc B", button_name="Xoá", candidate_id="c0")]
    decision = await healer.recover(descriptor, drifted, context())
    assert decision.recovered is False
    assert decision.record.refusal_reason == "admission_rejected:entity_scope_mismatch"
    assert decision.recovered_target is None


@pytest.mark.asyncio
async def test_recovery_refuses_role_drift() -> None:
    from agentqa.contracts.identity import TargetDescriptor

    healer = build_healer(synthetic_profile())
    descriptor = TargetDescriptor(intent="note", role="textbox", name="Ghi chú")
    scene = [SceneCandidate(candidate_id="c0", role="button", name="Ghi chú", text="Ghi chú")]
    decision = await healer.recover(descriptor, scene, context(operation=Operation.FILL))
    assert decision.recovered is False
    assert decision.record.refusal_reason == "admission_rejected:role_mismatch"


@pytest.mark.asyncio
async def test_model_ranker_uses_scripted_answer_within_candidate_set() -> None:
    profile = synthetic_profile(ranker="llm")
    jev = FakeJev(
        ScriptedJevReply(
            answers={
                "heal:delete_item": ChoiceAnswer(choice="c1", confidence=0.9, probabilities={"c0": 0.1, "c1": 0.9})
            }
        )
    )
    healer = build_healer(CalibrationProfile.model_validate(profile), decision=jev)
    descriptor = delete_descriptor("Việc A")
    scene = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Xoá mục", candidate_id="c1", attributes={"data-testid": "delete-a"}),
    ]
    decision = await healer.recover(descriptor, scene, context())
    assert decision.recovered is True
    assert decision.record.ranking is not None
    assert decision.record.ranking.ranker == RankerKind.LLM
    assert decision.record.ranking.scores[0].candidate_id == "c1"
    assert jev.requests[0].questions[0].question_id == "heal:delete_item"


@pytest.mark.asyncio
async def test_model_ranker_none_sentinel_refuses_without_guessing() -> None:
    profile = synthetic_profile(ranker="llm")
    jev = FakeJev(ScriptedJevReply(answers={"heal:delete_item": ChoiceAnswer(choice="none", confidence=0.99)}))
    healer = build_healer(CalibrationProfile.model_validate(profile), decision=jev)
    decision = await healer.recover(delete_descriptor("Việc A"), [delete_scene("Việc A")], context())
    assert decision.recovered is False
    assert decision.record.refusal_reason == "model_none"


@pytest.mark.asyncio
async def test_model_ranker_rejects_answer_outside_candidate_set() -> None:
    profile = synthetic_profile(ranker="llm")
    jev = FakeJev(ScriptedJevReply(answers={"heal:delete_item": ChoiceAnswer(choice="c99", confidence=0.99)}))
    healer = build_healer(CalibrationProfile.model_validate(profile), decision=jev)
    decision = await healer.recover(delete_descriptor("Việc A"), [delete_scene("Việc A")], context())
    assert decision.recovered is False
    assert decision.record.refusal_reason is not None
    assert decision.record.refusal_reason.startswith("unknown_candidate")


@pytest.mark.asyncio
async def test_model_ranker_missing_answer_is_refused() -> None:
    profile = synthetic_profile(ranker="llm")
    healer = build_healer(CalibrationProfile.model_validate(profile), decision=FakeJev(ScriptedJevReply()))
    decision = await healer.recover(delete_descriptor("Việc A"), [delete_scene("Việc A")], context())
    assert decision.recovered is False
    assert decision.record.refusal_reason == "missing_answer:Thiếu answer cho câu hỏi healing"


@pytest.mark.asyncio
async def test_cascade_escalates_only_when_heuristic_is_insufficient() -> None:
    profile = CalibrationProfile.model_validate(synthetic_profile(ranker="cascade", margin_min=0.9))
    jev = FakeJev(ScriptedJevReply(answers={"heal:delete_item": ChoiceAnswer(choice="c0", confidence=0.95)}))
    healer = build_healer(profile, decision=jev)
    twins = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c1"),
    ]
    decision = await healer.recover(delete_descriptor("Việc A"), twins, context())
    assert jev.remaining == 0
    assert decision.recovered is False
    assert decision.record.refusal_reason == "duplicate_identity"
    assert decision.record.ranking is not None
    assert decision.record.ranking.ranker == RankerKind.CASCADE

    p2 = CalibrationProfile.model_validate(synthetic_profile(ranker="cascade"))
    jev2 = FakeJev()
    healer2 = build_healer(p2, decision=jev2)
    confident = [delete_scene("Việc A", button_name="Xoá", candidate_id="c0")]
    decision2 = await healer2.recover(delete_descriptor("Việc A"), confident, context())
    assert decision2.recovered is True
    assert jev2.remaining == 1


def test_heuristic_ranker_ignores_model_port() -> None:
    ranker = build_ranker(synthetic_profile(), None)
    assert isinstance(ranker, HeuristicRanker) or type(ranker).__name__ == "AsyncHeuristicRanker"


def test_build_runtime_target_uses_current_candidate_attributes() -> None:
    descriptor = delete_descriptor("Việc A")
    candidate = SceneCandidate(
        candidate_id="c0",
        role="button",
        name="Xoá việc",
        entity_text="Việc A Chưa xong",
        attributes={"id": "row-3-delete"},
    )
    target = build_runtime_target(descriptor, candidate)
    assert target.locators[0].kind == LocatorKind.CSS
    assert target.locators[0].value == "#row-3-delete"
    assert target.name == "Xoá việc"
    assert target.attributes == {}
