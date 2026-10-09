from __future__ import annotations

import json
from uuid import uuid4

from agentqa.agent.observation.semantic import (
    RawCandidate,
    RawScene,
    SemanticObservationBuilder,
)
from agentqa.contracts.observation import Actionability, Modality
from agentqa.contracts.values import Taint


class Registry:
    def __init__(self, values: list[str] | None = None) -> None:
        self._values = set(values or [])

    def register(self, value: str) -> None:
        self._values.add(value)

    def find(self, payload: object) -> list[str]:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return [value for value in self._values if value in text]


def build_scene(*candidates: RawCandidate, scene_version: int = 1, frame_key: str | None = None) -> RawScene:
    return RawScene(
        url="http://127.0.0.1:9000/tasks?token=secret-token",
        title="Taskboard",
        scene_version=scene_version,
        frame_key=frame_key,
        candidates=list(candidates),
    )


def build(builder: SemanticObservationBuilder, scene: RawScene, **kwargs):
    return builder.build(
        scene,
        observation_id=uuid4(),
        version=1,
        session_key="sess-1",
        page_key="main",
        **kwargs,
    )


def test_snapshot_exports_role_state_visibility_with_opaque_refs() -> None:
    scene = build_scene(
        RawCandidate(source_id="node-1", role="button", name="Đăng nhập"),
        RawCandidate(
            source_id="node-2",
            role="textbox",
            name="Tên việc",
            enabled=False,
            actionability=Actionability.DISABLED,
        ),
        RawCandidate(
            source_id="node-3",
            role="checkbox",
            name="Hoàn thành",
            checked=True,
            selected=True,
        ),
        RawCandidate(
            source_id="node-4",
            role="button",
            name="Nút ẩn",
            visible=False,
            actionability=Actionability.OFFSCREEN,
        ),
    )
    snapshot, audit = build(SemanticObservationBuilder(), scene)
    assert [candidate.candidate_id for candidate in snapshot.candidates] == ["c0", "c1", "c2", "c3"]
    assert snapshot.candidates[0].role == "button"
    assert snapshot.candidates[1].state.enabled is False
    assert snapshot.candidates[1].actionability is Actionability.DISABLED
    assert snapshot.candidates[2].state.checked is True
    assert snapshot.candidates[2].state.selected is True
    assert snapshot.candidates[3].visible is False
    assert snapshot.candidates[3].actionability is Actionability.OFFSCREEN
    assert "node-1" not in json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
    assert audit.modality is Modality.SEMANTIC
    assert audit.contains_semantic_dom is True


def test_secret_tainted_values_are_not_exported() -> None:
    registry = Registry(["S3cret-Pass!"])
    scene = build_scene(
        RawCandidate(
            source_id="node-1",
            role="textbox",
            name="Mật khẩu",
            text="S3cret-Pass!",
            attributes={"type": "password"},
        ),
        RawCandidate(source_id="node-2", role="button", name="Gửi"),
    )
    builder = SemanticObservationBuilder(taint=registry)
    snapshot, audit = build(builder, scene)
    secret_candidate = snapshot.candidates[0]
    assert secret_candidate.taint is Taint.SECRET
    assert secret_candidate.text == ""
    assert secret_candidate.name == ""
    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
    assert "S3cret-Pass!" not in payload
    assert audit.canary_clear is True


def test_entity_keys_are_hashed_not_raw() -> None:
    scene = build_scene(
        RawCandidate(source_id="n1", role="listitem", name="Task A", entity_key="task-42", region="row:task-42")
    )
    snapshot, _audit = build(SemanticObservationBuilder(), scene)
    candidate = snapshot.candidates[0]
    assert candidate.entity_key is not None
    assert candidate.entity_key.startswith("e")
    assert candidate.entity_key != "task-42"
    assert "task-42" not in json.dumps(snapshot.model_dump(mode="json"))


def test_regions_group_candidates() -> None:
    scene = build_scene(
        RawCandidate(source_id="n1", role="listitem", name="Task A", region="row:1"),
        RawCandidate(source_id="n2", role="button", name="Xoá", region="row:1"),
        RawCandidate(source_id="n3", role="button", name="Thêm", region=None),
    )
    snapshot, _audit = build(SemanticObservationBuilder(), scene)
    assert len(snapshot.regions) == 1
    region = snapshot.regions[0]
    assert region.region_id.startswith("row:e")
    assert "row:1" not in json.dumps(snapshot.model_dump(mode="json"))
    assert region.candidate_ids == ["c0", "c1"]


def test_url_redaction_applies_to_snapshot() -> None:
    registry = Registry(["secret-token"])
    scene = build_scene(RawCandidate(source_id="n1", role="button", name="A"))
    snapshot, _audit = build(SemanticObservationBuilder(redactor=_redactor(registry)), scene)
    assert "secret-token" not in snapshot.url
    assert "REDACTED" in snapshot.url


def _redactor(registry: Registry):
    class PlainRedactor:
        def redact_text(self, text: str) -> str:
            for value in ("secret-token",):
                text = text.replace(value, "[REDACTED]")
            return text

    return PlainRedactor()
