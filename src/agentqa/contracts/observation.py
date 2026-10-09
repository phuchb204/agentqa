from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import JsonValue, StrictModel, Taint


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


class Actionability(StrEnum):
    ACTIONABLE = "actionable"
    OBSCURED = "obscured"
    DISABLED = "disabled"
    OFFSCREEN = "offscreen"
    UNKNOWN = "unknown"


class CandidateState(StrictModel):
    enabled: bool = True
    checked: bool | None = None
    selected: bool | None = None
    expanded: bool | None = None


class SemanticCandidate(StrictModel):
    candidate_id: str
    role: str
    name: str
    state: CandidateState = CandidateState()
    region: str | None = None
    visible: bool = True
    actionability: Actionability = Actionability.UNKNOWN
    text: str = ""
    entity_key: str | None = None
    taint: Taint = Taint.PUBLIC
    provenance: str = "dom"

    @field_validator("candidate_id")
    @classmethod
    def require_opaque_candidate_id(cls, value: str) -> str:
        if not value or not value.startswith("c") or not value[1:].isdigit():
            raise AgentQAValidationError(
                [field_error(("candidate_id",), ErrorCode.INPUT_INVALID, "Candidate ID phải có dạng c<n>")]
            )
        return value


class SemanticRegion(StrictModel):
    region_id: str
    kind: str
    label: str | None = None
    candidate_ids: list[str] = []


class BudgetProfile(StrictModel):
    profile_id: str
    version: str
    max_candidates: int
    max_bytes: int
    max_tokens: int
    max_image_bytes: int

    @field_validator("max_candidates", "max_bytes", "max_tokens", "max_image_bytes")
    @classmethod
    def require_positive(cls, value: int) -> int:
        if value <= 0:
            raise AgentQAValidationError(
                [field_error(("budget_profile",), ErrorCode.INPUT_INVALID, "Budget phải dương")]
            )
        return value


class BudgetManifest(StrictModel):
    profile_id: str
    profile_version: str
    retained: list[str] = []
    dropped: list[str] = []
    kept_bytes: int = 0
    dropped_bytes: int = 0
    estimated_tokens: int = 0
    truncated: bool = False
    none_context_sentinel: bool = False
    reason: str | None = None


class SemanticSnapshot(StrictModel):
    observation_id: UUID
    version: int
    session_key: str
    page_key: str
    frame_key: str | None = None
    scene_version: int
    url: str = ""
    title: str | None = None
    candidates: list[SemanticCandidate] = []
    regions: list[SemanticRegion] = []
    budget: BudgetManifest
    redaction: RedactionStatus
    taint: Taint = Taint.PUBLIC

    @field_validator("version")
    @classmethod
    def require_positive_version(cls, value: int) -> int:
        if value < 1:
            raise AgentQAValidationError(
                [field_error(("version",), ErrorCode.INPUT_INVALID, "Observation version phải >= 1")]
            )
        return value


class VisionMark(StrictModel):
    marker_id: str
    x: float
    y: float
    width: float
    height: float


class VisionViewport(StrictModel):
    width: int
    height: int
    dpr: float = 1.0
    scroll_x: float = 0.0
    scroll_y: float = 0.0


class VisionSnapshot(StrictModel):
    observation_id: UUID
    version: int
    session_key: str
    page_key: str
    frame_key: str | None = None
    scene_version: int
    image_ref: str
    image_digest: str
    image_bytes: int
    marks: list[VisionMark] = []
    viewport: VisionViewport
    layout_digest: str
    redaction: RedactionStatus = RedactionStatus.REDACTED


class ModalityAudit(StrictModel):
    observation_id: UUID
    modality: Modality
    payload_digest: str
    payload_bytes: int
    image_digest: str | None = None
    image_bytes: int | None = None
    contains_semantic_dom: bool
    canary_clear: bool
    scene_version: int


class HybridTrigger(StrEnum):
    VISUAL_TARGET = "visual_target"
    VISUAL_REF = "visual_ref"
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    STRUCTURED_NEED_CONTEXT = "structured_need_context"


class HybridDecision(StrictModel):
    use_image: bool
    triggers: list[HybridTrigger] = []
    reason: str
    blocked_capability: str | None = None
    cost_ref: str | None = None


class ObservationEnvelope(StrictModel):
    semantic: SemanticSnapshot | None = None
    vision: VisionSnapshot | None = None
    modality: Modality
    triggers: list[HybridTrigger] = []
    audit: ModalityAudit
    payload: dict[str, JsonValue] = Field(default_factory=dict)
