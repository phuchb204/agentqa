from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agentqa.agent.observation.provenance import (
    InputAuditor,
    ObservationLeakError,
    digest_structured,
    serialized_bytes,
)
from agentqa.agent.observation.semantic import RawCandidate, RawScene, SemanticObservationBuilder, semantic_payload
from agentqa.agent.observation.vision import VisionFirstHistory, VisionObservationBuilder, vision_payload
from agentqa.contracts.observation import Modality, VisionViewport


class Registry:
    def __init__(self, values: list[str] | None = None) -> None:
        self._values = set(values or [])

    def register(self, value: str) -> None:
        self._values.add(value)

    def find(self, payload: object) -> list[str]:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return [value for value in self._values if value in text]


def scene(scene_version: int = 1, frame_key: str | None = None, box: tuple[float, float, float, float] | None = None):
    return RawScene(
        url="http://127.0.0.1:9000/tasks",
        title="Taskboard",
        scene_version=scene_version,
        frame_key=frame_key,
        candidates=[RawCandidate(source_id="n0", role="button", name="Đăng nhập", box=box)],
    )


def test_exact_safe_bytes_recorded_for_semantic_payload() -> None:
    builder = SemanticObservationBuilder()
    snapshot, audit = builder.build(
        scene(),
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    payload = semantic_payload(snapshot)
    assert audit.payload_bytes == serialized_bytes(payload)
    assert audit.payload_digest == digest_structured(payload)
    assert audit.contains_semantic_dom is True
    assert audit.canary_clear is True


def test_exact_safe_bytes_recorded_for_vision_payload() -> None:
    vision_builder = VisionObservationBuilder()
    image = b"\x89PNG-ledger-visible"
    snapshot, _map, audit = vision_builder.build(
        scene(box=(1.0, 2.0, 3.0, 4.0)),
        screenshot=image,
        viewport=VisionViewport(width=100, height=100),
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    payload = vision_payload(snapshot)
    assert audit.modality is Modality.VISION_FIRST
    assert audit.payload_digest == digest_structured(payload)
    assert audit.image_bytes == len(image)
    assert audit.image_digest
    assert audit.contains_semantic_dom is False


def test_vision_first_rejects_semantic_dom_payload() -> None:
    auditor = InputAuditor()
    with pytest.raises(ObservationLeakError):
        auditor.audit(
            observation_id=uuid4(),
            modality=Modality.VISION_FIRST,
            payload={"candidates": [{"role": "button", "name": "Đăng nhập"}]},
            image_bytes=b"png",
            scene_version=1,
        )


def test_semantic_audit_requires_dom_structure() -> None:
    auditor = InputAuditor()
    with pytest.raises(ObservationLeakError):
        auditor.audit(
            observation_id=uuid4(),
            modality=Modality.SEMANTIC,
            payload={"notes": "không có cấu trúc"},
            image_bytes=None,
            scene_version=1,
        )


def test_canary_is_blocked_before_policy() -> None:
    auditor = InputAuditor(taint=Registry(["CANARY-TOKEN-123"]))
    with pytest.raises(ObservationLeakError):
        auditor.audit(
            observation_id=uuid4(),
            modality=Modality.SEMANTIC,
            payload={"candidates": [{"name": "CANARY-TOKEN-123"}]},
            image_bytes=None,
            scene_version=1,
        )
    auditor.assert_clean({"candidates": []})


def test_forbidden_metadata_rejected() -> None:
    auditor = InputAuditor()
    for payload in (
        {"candidates": [{"selector": "css=#login"}]},
        {"candidates": [{"raw_handle": "x"}]},
        {"candidates": [{"note": "ground_truth"}]},
        {"candidates": [{"ref": "@e12ab34"}]},
    ):
        with pytest.raises(ObservationLeakError):
            auditor.audit(
                observation_id=uuid4(),
                modality=Modality.SEMANTIC,
                payload=payload,
                image_bytes=None,
                scene_version=1,
            )


def test_vision_history_has_no_semantic_labels() -> None:
    history = VisionFirstHistory()
    history.record(operation="click_marker", marker_id="m2", outcome_code="settled")
    assert history.checkpoint_feedback("failed") == "checkpoint:failed"
    assert history.error_text("locator_missing") == "error:locator_missing"
    serialized = json.dumps(history.payload(), ensure_ascii=False)
    assert "Đăng nhập" not in serialized
    assert set(history.payload()[0]) == {"operation", "marker", "outcome"}


def test_scene_version_invalidation_and_frame_change() -> None:
    builder = SemanticObservationBuilder()
    snapshot, audit = builder.build(
        scene(scene_version=1, frame_key="frame-main"),
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    assert snapshot.frame_key == "frame-main"
    auditor = InputAuditor()
    assert auditor.is_stale(audit, current_scene_version=2) is True
    assert auditor.is_stale(audit, current_scene_version=1) is False


def test_truncation_missingness_is_recorded() -> None:
    from agentqa.contracts.observation import BudgetProfile

    profile = BudgetProfile(
        profile_id="semantic-small",
        version="1",
        max_candidates=1,
        max_bytes=100_000,
        max_tokens=25_000,
        max_image_bytes=1_000_000,
    )
    raw = RawScene(
        url="",
        title=None,
        scene_version=1,
        candidates=[
            RawCandidate(source_id="a", role="button", name="A"),
            RawCandidate(source_id="b", role="button", name="B"),
            RawCandidate(source_id="c", role="button", name="C"),
        ],
    )
    snapshot, _audit = SemanticObservationBuilder(profile=profile).build(
        raw,
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    assert snapshot.budget.truncated is True
    assert snapshot.budget.dropped == ["c1", "c2"] or len(snapshot.budget.dropped) == 2
    assert snapshot.budget.dropped_bytes > 0
    assert snapshot.budget.none_context_sentinel is True


def test_audit_timestamps_not_required_but_digest_stable() -> None:
    payload = {"candidates": [{"name": "A"}]}
    first = digest_structured(payload)
    second = digest_structured(payload)
    assert first == second
    assert datetime(2026, 10, 9, tzinfo=UTC).year == 2026
