from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import field_validator, model_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import StrictModel


class Modality(StrEnum):
    SEMANTIC = "semantic"
    IMAGE = "image"
    HYBRID = "hybrid"
    VISION_FIRST = "vision_first"


class RedactionStatus(StrEnum):
    NONE = "none"
    REDACTED = "redacted"
    FAILED = "failed"


class TruncationManifest(StrictModel):
    dropped_regions: list[str] = []
    reason: str | None = None
    dropped_bytes: int = 0


class Observation(StrictModel):
    observation_id: UUID
    version: int
    session_key: str
    page_key: str
    frame_key: str | None = None
    observed_at: datetime
    mode: Modality
    semantic_ref: str | None = None
    image_ref: str | None = None
    candidate_refs: list[str] = []
    size_bytes: int
    redaction: RedactionStatus
    truncation: TruncationManifest | None = None

    @field_validator("observed_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AgentQAValidationError(
                [field_error(("observed_at",), ErrorCode.INPUT_INVALID, "Timestamp phải có timezone")]
            )
        return value

    @field_validator("version")
    @classmethod
    def require_positive_version(cls, value: int) -> int:
        if value < 1:
            raise AgentQAValidationError(
                [field_error(("version",), ErrorCode.INPUT_INVALID, "Observation version phải >= 1")]
            )
        return value

    @model_validator(mode="after")
    def require_modality_refs(self) -> Observation:
        if self.mode in (Modality.SEMANTIC, Modality.HYBRID, Modality.VISION_FIRST) and not self.semantic_ref:
            raise AgentQAValidationError(
                [field_error(("semantic_ref",), ErrorCode.INPUT_INVALID, "Mode cần semantic_ref")]
            )
        if self.mode in (Modality.IMAGE, Modality.HYBRID, Modality.VISION_FIRST) and not self.image_ref:
            raise AgentQAValidationError([field_error(("image_ref",), ErrorCode.INPUT_INVALID, "Mode cần image_ref")])
        return self


class ProbeOutcome(StrictModel):
    satisfied: bool
    evidence_ref: str | None = None
    error_code: ErrorCode | None = None
