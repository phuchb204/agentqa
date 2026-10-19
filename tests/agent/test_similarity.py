from __future__ import annotations

import pytest

from agentqa.agent.healing import HeuristicRanker, RankContext, candidate_features, name_similarity, score_candidates
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.calibration import CalibrationEvidence, CalibrationProfile, FeatureWeights, HealingReadiness
from agentqa.contracts.errors import AgentQAValidationError
from agentqa.contracts.healing import RankingOutcome
from agentqa.contracts.identity import TargetDescriptor
from tests.support.healing import delete_descriptor, delete_scene, measured_profile, synthetic_profile


def test_name_similarity_orders_exact_over_contains_over_partial() -> None:
    assert name_similarity("Xoá", "Xoá") == 1.0
    assert name_similarity("Xoá", "xoá") == 1.0
    assert name_similarity("Xoá", "Xoá việc") == 0.7
    assert name_similarity("Xoá", "Đổi trạng thái") < 0.5
    assert name_similarity("Xoá", None) == 0.0
    assert name_similarity(None, "Xoá") is None


def test_features_keep_missing_flags_instead_of_zero_scoring() -> None:
    descriptor = TargetDescriptor(intent="submit", role="button")
    candidate = SceneCandidate(candidate_id="c0", role="button", name="Gửi")
    features = candidate_features(descriptor, candidate, frame_key=None)
    assert "name" in features.missing
    assert "context" in features.missing
    assert "stable_attribute" in features.missing
    assert "geometry" in features.missing
    assert "role" in features.scores
    assert "name" not in features.scores


def test_ranker_uses_weights_on_the_same_scoped_candidates() -> None:
    profile = synthetic_profile(
        weights=FeatureWeights(role=0.05, name=1.0, context=0.05, stable_attribute=0.0, geometry=0.0).model_dump()
    )
    ranker = HeuristicRanker(CalibrationProfile.model_validate(profile))
    descriptor = delete_descriptor("Việc A")
    scene = [
        delete_scene("Việc A", button_name="Xoá việc", candidate_id="c0"),
        delete_scene("Việc A", button_name="Đổi trạng thái", candidate_id="c1"),
    ]
    ranking = ranker.rank(descriptor, scene, RankContext(node_id="n1", operation=Operation.CLICK))
    assert ranking.outcome == RankingOutcome.RECOVER
    assert ranking.scores[0].candidate_id == "c0"
    assert ranking.margin is not None and ranking.margin > 0
    assert "name_similarity" in " ".join(ranking.scores[0].reasons)


def test_hard_constraints_filter_frame_and_stateful_candidates() -> None:
    ranker = HeuristicRanker(synthetic_profile())
    descriptor = delete_descriptor("Việc A")
    scene = [
        delete_scene("Việc A", candidate_id="c0", frame_key="main"),
        delete_scene("Việc A", candidate_id="c1", frame_key="other"),
        delete_scene("Việc A", candidate_id="c2", enabled=False),
    ]
    ranking = ranker.rank(descriptor, scene, RankContext(node_id="n1", operation=Operation.CLICK, frame_key="main"))
    kept = {item.candidate_id for item in ranking.scores}
    assert kept == {"c0"}
    read_ranking = ranker.rank(descriptor, scene, RankContext(node_id="n1", operation=None, frame_key="main"))
    assert {item.candidate_id for item in read_ranking.scores} == {"c0", "c2"}


def test_thresholds_produce_refusal_and_need_context() -> None:
    strict = HeuristicRanker(synthetic_profile(min_score=0.99))
    descriptor = delete_descriptor("Việc A")
    scene = [delete_scene("Việc A", button_name="Xóa")]
    low = strict.rank(descriptor, scene, RankContext(node_id="n1", operation=Operation.CLICK))
    assert low.outcome == RankingOutcome.REFUSE
    assert low.reason == "low_score"

    ambiguous = HeuristicRanker(synthetic_profile(margin_min=0.5))
    twins = [
        SceneCandidate(candidate_id="c0", role="button", name="Xóa", entity_text="Việc A"),
        SceneCandidate(candidate_id="c1", role="button", name="Xóa", entity_text="Việc A"),
    ]
    tie = ambiguous.rank(descriptor, twins, RankContext(node_id="n1", operation=Operation.CLICK))
    assert tie.outcome == RankingOutcome.REFUSE
    assert tie.reason == "ambiguous_margin"

    blind = HeuristicRanker(synthetic_profile(min_coverage=0.9))
    sparse = TargetDescriptor(intent="mystery")
    sparse_scene = [SceneCandidate(candidate_id="c0", role="button")]
    context = blind.rank(sparse, sparse_scene, RankContext(node_id="n1", operation=None))
    assert context.outcome == RankingOutcome.NEED_MORE_CONTEXT
    assert context.reason == "missing_features"

    none = blind.rank(descriptor, [], RankContext(node_id="n1", operation=Operation.CLICK))
    assert none.outcome == RankingOutcome.NONE
    assert none.reason == "no_candidate"


def test_duplicate_identity_refuses_despite_passing_margin() -> None:
    from agentqa.agent.healing import RankContext
    from agentqa.agent.healing.ranker import HeuristicRanker, has_duplicate_identity
    from agentqa.contracts.identity import TargetDescriptor
    from tests.support.healing import scope

    profile = synthetic_profile(
        weights={"role": 0.1, "name": 0.2, "context": 0.1, "stable_attribute": 0.6, "geometry": 0.0}
    )
    ranker = HeuristicRanker(profile)
    descriptor = TargetDescriptor(
        intent="delete_item",
        role="button",
        name="Xoá",
        entity_scope=scope("Việc A"),
        attributes={"data-testid": "t1", "label": "xoa"},
    )
    twins = [
        SceneCandidate(
            candidate_id="c0",
            role="button",
            name="Xoá",
            entity_text="Việc A Chưa xong",
            attributes={"data-testid": "t1", "label": "xoa"},
        ),
        SceneCandidate(
            candidate_id="c1",
            role="button",
            name="Xoá",
            entity_text="Việc A Chưa xong",
            attributes={"data-testid": "t2", "label": "xoa"},
        ),
    ]
    ranking = ranker.rank(descriptor, twins, RankContext(node_id="n1", operation=Operation.CLICK))
    assert ranking.margin is not None and ranking.margin >= 0.15
    assert ranking.outcome == RankingOutcome.REFUSE
    assert ranking.reason == "duplicate_identity"

    assert has_duplicate_identity(descriptor, []) is False
    assert (
        has_duplicate_identity(
            descriptor,
            [
                (twins[0], ranking.scores[0], None),
            ],
        )
        is False
    )


def test_duplicate_identity_ignores_scope_at_ranker_level() -> None:
    # Ranker từ chối khi tên ghi nhận trùng lặp trên trang, không dùng scope để nới lỏng:
    # thu hẹp scope là việc của guard (chạy trước healer); ranker chỉ thấy ca guard đã thất bại.
    from agentqa.agent.healing import RankContext
    from agentqa.agent.healing.ranker import HeuristicRanker
    from agentqa.contracts.identity import TargetDescriptor
    from tests.support.healing import scope

    profile = synthetic_profile()
    ranker = HeuristicRanker(profile)
    descriptor = TargetDescriptor(intent="delete_item", role="button", name="Xoá", entity_scope=scope("Việc A"))
    scene = [
        delete_scene("Việc A", button_name="Xoá", candidate_id="c0"),
        delete_scene("Việc B", button_name="Xoá", candidate_id="c1"),
    ]
    ranking = ranker.rank(descriptor, scene, RankContext(node_id="n1", operation=Operation.CLICK))
    assert ranking.outcome == RankingOutcome.REFUSE
    assert ranking.reason == "duplicate_identity"
    assert ranking.scores[0].candidate_id == "c0"


def test_candidate_truncation_manifest_records_total() -> None:
    ranker = HeuristicRanker(synthetic_profile(max_candidates=3))
    descriptor = delete_descriptor("Việc A")
    scene = [delete_scene("Việc A", candidate_id=f"c{index}") for index in range(7)]
    ranking = ranker.rank(descriptor, scene, RankContext(node_id="n1", operation=Operation.CLICK))
    assert ranking.truncated is True
    assert ranking.total_candidates == 7
    assert len(ranking.scores) == 3


def test_scored_candidates_carry_missingness_and_coverage() -> None:
    profile = synthetic_profile()
    descriptor = TargetDescriptor(intent="row", role="listitem")
    scene = [SceneCandidate(candidate_id="c0", role="listitem", entity_text="Việc A")]
    scored = score_candidates(descriptor, scene, profile, RankContext(node_id="n1"))
    assert scored[0][1].missing
    assert scored[0][2].coverage < 1.0


def test_synthetic_profile_is_never_production_ready() -> None:
    profile = synthetic_profile(min_score=0.99)
    assert profile.production_ready() is False
    readiness = HealingReadiness.from_profile(profile)
    assert readiness.verified is False
    assert readiness.reason == "synthetic_profile"
    assert readiness.profile_id == profile.profile_id


def test_measured_profile_requires_receipt_and_bounds() -> None:
    with pytest.raises(AgentQAValidationError):
        CalibrationProfile.model_validate(measured_profile(receipt_ref=None))
    with pytest.raises(AgentQAValidationError):
        CalibrationProfile.model_validate(measured_profile(bounds={}))
    profile = CalibrationProfile.model_validate(measured_profile())
    assert profile.evidence == CalibrationEvidence.MEASURED
    assert profile.production_ready() is True
    assert HealingReadiness.from_profile(profile).reason == "calibrated"
