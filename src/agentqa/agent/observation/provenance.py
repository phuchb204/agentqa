from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from agentqa.contracts.canonical import canonicalize, digest_artifact_bytes
from agentqa.contracts.observation import Modality, ModalityAudit
from agentqa.contracts.values import Taint

FORBIDDEN_METADATA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bjs="),
    re.compile(r"\bcss="),
    re.compile(r"\bxpath="),
    re.compile(r"raw_handle"),
    re.compile(r"ground_truth"),
    re.compile(r"@e[0-9a-f]{4,}"),
)

SEMANTIC_DOM_KEYS = ("candidates", "aria", "dom_text", "accessible_tree")


class ObservationLeakError(RuntimeError):
    def __init__(self, message: str, sink: str = "observation_input") -> None:
        self.sink = sink
        super().__init__((message, sink))


class Redactor(Protocol):
    def redact_text(self, text: str) -> str: ...


class TaintChecks(Protocol):
    def find(self, payload: object) -> list[str]: ...

    def register(self, value: str) -> None: ...


class NullRedactor:
    def redact_text(self, text: str) -> str:
        return text


def digest_payload_text(payload: str) -> str:
    return digest_artifact_bytes(payload.encode("utf-8"))


def digest_structured(payload: object) -> str:
    return digest_artifact_bytes(canonicalize(payload))


def serialized_bytes(payload: object) -> int:
    return len(canonicalize(payload))


def _has_semantic_dom(payload: object) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in SEMANTIC_DOM_KEYS:
                return True
            if _has_semantic_dom(value):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(_has_semantic_dom(item) for item in payload)
    return False


class InputAuditor:
    def __init__(
        self,
        *,
        taint: TaintChecks | None = None,
        forbidden: Iterable[re.Pattern[str]] = FORBIDDEN_METADATA_PATTERNS,
        redactor: Redactor | None = None,
    ) -> None:
        self._taint = taint
        self._forbidden = tuple(forbidden)
        self._redactor = redactor or NullRedactor()

    def audit(
        self,
        *,
        observation_id: UUID,
        modality: Modality,
        payload: object,
        image_bytes: bytes | None,
        scene_version: int,
    ) -> ModalityAudit:
        data = canonicalize(payload)
        text = data.decode("utf-8", errors="replace")
        if self._taint is not None:
            found = self._taint.find(payload)
            if found:
                raise ObservationLeakError("Canary bị chặn trước khi gửi policy")
        for pattern in self._forbidden:
            if pattern.search(text):
                raise ObservationLeakError(f"Metadata bị cấm lọt vào observation: {pattern.pattern}")
        contains_semantic_dom = _has_semantic_dom(payload)
        if modality is Modality.VISION_FIRST and contains_semantic_dom:
            raise ObservationLeakError("Vision-first input chứa semantic DOM")
        if modality is Modality.SEMANTIC and not contains_semantic_dom:
            raise ObservationLeakError("Semantic input thiếu cấu trúc DOM đã kiểm")
        image_digest = digest_artifact_bytes(image_bytes) if image_bytes is not None else None
        return ModalityAudit(
            observation_id=observation_id,
            modality=modality,
            payload_digest=digest_artifact_bytes(data),
            payload_bytes=len(data),
            image_digest=image_digest,
            image_bytes=len(image_bytes) if image_bytes is not None else None,
            contains_semantic_dom=contains_semantic_dom,
            canary_clear=True,
            scene_version=scene_version,
        )

    def assert_clean(self, payload: object, sink: str = "observation_input") -> None:
        if self._taint is not None and self._taint.find(payload):
            raise ObservationLeakError("Canary bị chặn", sink)
        text = canonicalize(payload).decode("utf-8", errors="replace")
        for pattern in self._forbidden:
            if pattern.search(text):
                raise ObservationLeakError(f"Metadata bị cấm: {pattern.pattern}", sink)

    def is_stale(self, audit: ModalityAudit, current_scene_version: int) -> bool:
        return audit.scene_version != current_scene_version


TAINT_ORDER = {Taint.PUBLIC: 0, Taint.INTERNAL: 1, Taint.SECRET: 2}


def max_taint(values: Iterable[Taint]) -> Taint:
    return max(values, key=lambda item: TAINT_ORDER[item], default=Taint.PUBLIC)
