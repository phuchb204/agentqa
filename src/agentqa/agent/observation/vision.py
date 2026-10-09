from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID

from agentqa.agent.observation.provenance import InputAuditor
from agentqa.agent.observation.semantic import RawScene
from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.observation import (
    Modality,
    ModalityAudit,
    RedactionStatus,
    VisionMark,
    VisionSnapshot,
    VisionViewport,
)

VISION_SCRIPT_VERSION = 1


class ObservationBudgetError(RuntimeError):
    def __init__(self, message: str, code: ErrorCode = ErrorCode.RESOURCE_EXHAUSTED) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ExecutorHandle:
    marker_id: str
    candidate_ref: str
    source_id: str
    box: tuple[float, float, float, float]


@dataclass
class VisionMarkerMap:
    entries: dict[str, ExecutorHandle] = field(default_factory=dict)
    layout_digest: str = ""

    def resolve(self, marker_id: str) -> ExecutorHandle:
        if marker_id not in self.entries:
            raise KeyError(marker_id)
        return self.entries[marker_id]


class VisionObservationBuilder:
    def __init__(self, *, max_image_bytes: int = 1_500_000, auditor: InputAuditor | None = None) -> None:
        self._max_image_bytes = max_image_bytes
        self._auditor = auditor or InputAuditor()

    def build(
        self,
        scene: RawScene,
        *,
        screenshot: bytes,
        viewport: VisionViewport,
        observation_id: UUID,
        version: int,
        session_key: str,
        page_key: str,
        frame_key: str | None = None,
    ) -> tuple[VisionSnapshot, VisionMarkerMap, ModalityAudit]:
        if len(screenshot) > self._max_image_bytes:
            raise ObservationBudgetError("Ảnh vượt budget image bytes")
        marks: list[VisionMark] = []
        marker_map = VisionMarkerMap()
        for index, candidate in enumerate(scene.candidates):
            if candidate.box is None:
                continue
            marker_id = f"m{len(marks)}"
            x, y, width, height = candidate.box
            marks.append(VisionMark(marker_id=marker_id, x=x, y=y, width=width, height=height))
            marker_map.entries[marker_id] = ExecutorHandle(
                marker_id=marker_id,
                candidate_ref=f"c{index}",
                source_id=candidate.source_id,
                box=candidate.box,
            )
        layout_digest = _layout_digest(scene)
        marker_map.layout_digest = layout_digest
        snapshot = VisionSnapshot(
            observation_id=observation_id,
            version=version,
            session_key=session_key,
            page_key=page_key,
            frame_key=frame_key or scene.frame_key,
            scene_version=scene.scene_version,
            image_ref=f"vision://{observation_id}/viewport",
            image_digest=digest_artifact_bytes(screenshot),
            image_bytes=len(screenshot),
            marks=marks,
            viewport=viewport,
            layout_digest=layout_digest,
            redaction=RedactionStatus.REDACTED,
        )
        audit = self._auditor.audit(
            observation_id=observation_id,
            modality=Modality.VISION_FIRST,
            payload=vision_payload(snapshot),
            image_bytes=screenshot,
            scene_version=scene.scene_version,
        )
        return snapshot, marker_map, audit

    def revalidate(self, *, marker_id: str, layout_digest: str, scene: RawScene) -> bool:
        if layout_digest != _layout_digest(scene):
            return False
        return any(handle.marker_id == marker_id for handle in _marker_handles(scene))


class VisionFirstHistory:
    def __init__(self) -> None:
        self._entries: list[dict[str, str | None]] = []

    @property
    def entries(self) -> list[dict[str, str | None]]:
        return list(self._entries)

    def record(self, *, operation: str, marker_id: str | None, outcome_code: str) -> None:
        self._entries.append(
            {
                "operation": operation,
                "marker": marker_id,
                "outcome": outcome_code,
            }
        )

    def checkpoint_feedback(self, outcome_code: str) -> str:
        return f"checkpoint:{outcome_code}"

    def error_text(self, error_code: str) -> str:
        return f"error:{error_code}"

    def payload(self) -> list[dict[str, str | None]]:
        return [dict(entry) for entry in self._entries]


def vision_payload(snapshot: VisionSnapshot) -> dict:
    return {
        "observation_id": str(snapshot.observation_id),
        "version": snapshot.version,
        "scene_version": snapshot.scene_version,
        "image": {
            "ref": snapshot.image_ref,
            "digest": snapshot.image_digest,
            "bytes": snapshot.image_bytes,
        },
        "marks": [mark.model_dump(mode="json") for mark in snapshot.marks],
        "viewport": snapshot.viewport.model_dump(mode="json"),
        "layout_digest": snapshot.layout_digest,
    }


def _layout_digest(scene: RawScene) -> str:
    parts = [
        f"{candidate.source_id}:{candidate.box}"
        for candidate in sorted(scene.candidates, key=lambda item: item.source_id)
    ]
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def _marker_handles(scene: RawScene) -> list[ExecutorHandle]:
    handles: list[ExecutorHandle] = []
    for index, candidate in enumerate(scene.candidates):
        if candidate.box is None:
            continue
        handles.append(
            ExecutorHandle(
                marker_id=f"m{len(handles)}",
                candidate_ref=f"c{index}",
                source_id=candidate.source_id,
                box=candidate.box,
            )
        )
    return handles


__all__ = [
    "VISION_SCRIPT_VERSION",
    "ExecutorHandle",
    "ObservationBudgetError",
    "VisionFirstHistory",
    "VisionMarkerMap",
    "VisionObservationBuilder",
    "vision_payload",
]
