from __future__ import annotations

from uuid import uuid4

from agentqa.agent.observation.selection import (
    DEFAULT_SEMANTIC_PROFILE,
    NONE_CONTEXT_TEXT,
    BudgetSelector,
)
from agentqa.agent.observation.semantic import RawCandidate, RawScene, SemanticObservationBuilder
from agentqa.contracts.observation import BudgetProfile


def scene_with(count: int, prefix: str = "Nút") -> RawScene:
    return RawScene(
        url="http://127.0.0.1/",
        title=None,
        scene_version=1,
        candidates=[
            RawCandidate(source_id=f"n{index}", role="button", name=f"{prefix} {index}") for index in range(count)
        ],
    )


def build(builder: SemanticObservationBuilder, scene: RawScene, **kwargs):
    return builder.build(
        scene,
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
        **kwargs,
    )


def test_default_profile_is_versioned_and_not_hardcoded_8kb() -> None:
    assert DEFAULT_SEMANTIC_PROFILE.version == "2"
    assert DEFAULT_SEMANTIC_PROFILE.max_bytes != 8192
    assert DEFAULT_SEMANTIC_PROFILE.max_candidates > 0


def test_small_scene_has_no_truncation() -> None:
    snapshot, _audit = build(SemanticObservationBuilder(), scene_with(3))
    assert snapshot.budget.truncated is False
    assert snapshot.budget.none_context_sentinel is False
    assert snapshot.budget.dropped == []
    assert all(candidate.name != NONE_CONTEXT_TEXT for candidate in snapshot.candidates)


def test_truncation_keeps_manifest_sentinel_and_flag() -> None:
    profile = BudgetProfile(
        profile_id="semantic-test",
        version="7",
        max_candidates=5,
        max_bytes=100_000,
        max_tokens=25_000,
        max_image_bytes=1_000_000,
    )
    snapshot, _audit = build(SemanticObservationBuilder(profile=profile), scene_with(40))
    assert snapshot.budget.truncated is True
    assert snapshot.budget.none_context_sentinel is True
    assert snapshot.budget.reason is not None
    assert len(snapshot.budget.dropped) == 35
    assert snapshot.budget.dropped_bytes > 0
    assert any(candidate.name == NONE_CONTEXT_TEXT for candidate in snapshot.candidates)
    assert snapshot.budget.estimated_tokens > 0
    assert snapshot.budget.profile_id == "semantic-test"
    assert snapshot.budget.profile_version == "7"


def test_byte_budget_truncates_even_below_candidate_limit() -> None:
    profile = BudgetProfile(
        profile_id="semantic-bytes",
        version="1",
        max_candidates=100,
        max_bytes=400,
        max_tokens=100,
        max_image_bytes=1_000_000,
    )
    scene = RawScene(
        url="",
        title=None,
        scene_version=1,
        candidates=[RawCandidate(source_id=f"n{index}", role="button", name="x" * 200) for index in range(5)],
    )
    snapshot, _audit = build(SemanticObservationBuilder(profile=profile), scene)
    assert snapshot.budget.truncated is True
    assert snapshot.budget.dropped
    assert snapshot.budget.kept_bytes <= 400


def test_mandatory_and_subgoal_candidates_survive_truncation() -> None:
    profile = BudgetProfile(
        profile_id="semantic-test",
        version="1",
        max_candidates=2,
        max_bytes=100_000,
        max_tokens=25_000,
        max_image_bytes=1_000_000,
    )
    scene = RawScene(
        url="",
        title=None,
        scene_version=1,
        candidates=[
            RawCandidate(source_id="n0", role="button", name="Huỷ"),
            RawCandidate(source_id="n1", role="button", name="Đăng nhập ngay"),
            RawCandidate(source_id="n2", role="button", name="Thêm việc"),
            RawCandidate(source_id="n3", role="button", name="Khác"),
        ],
    )
    snapshot, _audit = build(
        SemanticObservationBuilder(profile=profile),
        scene,
        subgoal_terms=("đăng nhập",),
        mandatory_ids=frozenset({"c2"}),
    )
    names = [candidate.name for candidate in snapshot.candidates]
    assert "Đăng nhập ngay" in names
    assert "Thêm việc" in names


def test_expansion_adds_region_candidates_before_decision() -> None:
    selector = BudgetSelector(
        BudgetProfile(
            profile_id="semantic-test",
            version="1",
            max_candidates=2,
            max_bytes=100_000,
            max_tokens=25_000,
            max_image_bytes=1_000_000,
        )
    )
    builder = SemanticObservationBuilder(profile=selector.profile)
    snapshot, _audit = build(builder, scene_with(6, prefix="Mục"))
    assert snapshot.budget.truncated is True
    extra = [
        RawCandidate(source_id="e0", role="button", name="Mở rộng 1"),
        RawCandidate(source_id="e1", role="button", name="Mở rộng 2"),
    ]
    from agentqa.contracts.observation import SemanticCandidate

    expanded = selector.expand(
        snapshot,
        [SemanticCandidate(candidate_id="c9", role=item.role, name=item.name, provenance="dom") for item in extra],
    )
    assert expanded.budget.reason == "expanded:region"
    assert len(expanded.candidates) >= len(snapshot.candidates)
    assert any(candidate.name == "Mở rộng 1" for candidate in expanded.candidates)
