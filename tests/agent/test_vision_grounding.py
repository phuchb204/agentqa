from __future__ import annotations

import json
from uuid import uuid4

from agentqa.agent.observation.semantic import RawCandidate, RawScene
from agentqa.agent.observation.vision import ObservationBudgetError, VisionObservationBuilder, vision_payload
from agentqa.contracts.observation import VisionViewport

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic-safe-pixels" * 4


def viewport() -> VisionViewport:
    return VisionViewport(width=1280, height=720, dpr=1.5, scroll_x=0, scroll_y=120)


def scene(boxes: list[tuple[float, float, float, float]]) -> RawScene:
    return RawScene(
        url="http://127.0.0.1:9000/tasks",
        title="Taskboard",
        scene_version=3,
        candidates=[
            RawCandidate(source_id=f"node-{index}", role="button", name=f"Nút {index}", box=box)
            for index, box in enumerate(boxes)
        ],
    )


def build():
    builder = VisionObservationBuilder()
    return builder.build(
        scene([(10.0, 20.0, 100.0, 30.0), (10.0, 80.0, 100.0, 30.0)]),
        screenshot=PNG_BYTES,
        viewport=viewport(),
        observation_id=uuid4(),
        version=2,
        session_key="sess",
        page_key="main",
    )


def test_marks_are_numeric_geometry_with_dpr_scroll_metadata() -> None:
    snapshot, _marker_map, audit = build()
    assert [mark.marker_id for mark in snapshot.marks] == ["m0", "m1"]
    mark = snapshot.marks[0]
    assert (mark.x, mark.y, mark.width, mark.height) == (10.0, 20.0, 100.0, 30.0)
    assert snapshot.viewport.dpr == 1.5
    assert snapshot.viewport.scroll_y == 120
    assert snapshot.viewport.width == 1280
    assert snapshot.image_digest
    assert snapshot.image_bytes == len(PNG_BYTES)
    assert audit.image_bytes == len(PNG_BYTES)
    assert audit.contains_semantic_dom is False


def test_marker_map_is_private_not_in_payload() -> None:
    snapshot, marker_map, _audit = build()
    handle = marker_map.resolve("m0")
    assert handle.source_id == "node-0"
    assert handle.candidate_ref == "c0"
    payload_text = json.dumps(vision_payload(snapshot), ensure_ascii=False)
    assert "node-0" not in payload_text
    assert "source_id" not in payload_text
    assert "candidate_ref" not in payload_text


def test_revalidation_invalidates_after_layout_change() -> None:
    builder = VisionObservationBuilder()
    original = scene([(10.0, 20.0, 100.0, 30.0)])
    snapshot, marker_map, _audit = builder.build(
        original,
        screenshot=PNG_BYTES,
        viewport=viewport(),
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    assert builder.revalidate(marker_id="m0", layout_digest=snapshot.layout_digest, scene=original) is True
    moved = scene([(90.0, 220.0, 100.0, 30.0)])
    assert builder.revalidate(marker_id="m0", layout_digest=snapshot.layout_digest, scene=moved) is False
    assert marker_map.layout_digest == snapshot.layout_digest


def test_image_over_budget_is_blocked() -> None:
    builder = VisionObservationBuilder(max_image_bytes=16)
    try:
        builder.build(
            scene([(0.0, 0.0, 1.0, 1.0)]),
            screenshot=PNG_BYTES,
            viewport=viewport(),
            observation_id=uuid4(),
            version=1,
            session_key="s",
            page_key="main",
        )
    except ObservationBudgetError as error:
        assert "budget" in str(error)
    else:
        raise AssertionError("Ảnh vượt budget phải bị chặn")


def test_candidates_without_geometry_get_no_marker() -> None:
    builder = VisionObservationBuilder()
    raw = RawScene(
        url="",
        title=None,
        scene_version=1,
        candidates=[
            RawCandidate(source_id="a", role="button", name="Có box", box=(1.0, 1.0, 2.0, 2.0)),
            RawCandidate(source_id="b", role="button", name="Không box"),
        ],
    )
    snapshot, marker_map, _audit = builder.build(
        raw,
        screenshot=PNG_BYTES,
        viewport=viewport(),
        observation_id=uuid4(),
        version=1,
        session_key="s",
        page_key="main",
    )
    assert len(snapshot.marks) == 1
    assert marker_map.resolve("m0").source_id == "a"
