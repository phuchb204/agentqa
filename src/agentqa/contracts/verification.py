from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.observation import Observation
from agentqa.contracts.values import StrictModel, ValueExpr


class Comparator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    COUNT_EQUALS = "count_equals"
    COUNT_GREATER_OR_EQUAL = "count_greater_or_equal"
    EXISTS = "exists"
    UNIQUE = "unique"
    VISIBLE = "visible"
    HIDDEN = "hidden"
    ABSENT = "absent"
    TEXT_EQUALS = "text_equals"
    TEXT_MATCHES = "text_matches"
    VALUE_EQUALS = "value_equals"
    STATE_CHECKED = "state_checked"
    STATE_ENABLED = "state_enabled"
    ATTRIBUTE_EQUALS = "attribute_equals"
    URL_PATH_EQUALS = "url_path_equals"
    URL_EQUALS = "url_equals"
    NETWORK_REQUEST = "network_request"
    DOWNLOAD_MATCHES = "download_matches"
    VISUAL_MATCH = "visual_match"


class AssertionStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NOT_EVALUATED = "not_evaluated"


class EvidenceStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    REDACTION_FAILED = "redaction_failed"


class EvidenceRequirement(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class WaitPolicy(StrictModel):
    timeout_ms: int
    poll_ms: int = 100


class NetworkFilter(StrictModel):
    method: str | None = None
    path_contains: str | None = None
    status: int | None = None
    body_contains: str | None = None
    minimum_count: int = 1

    @model_validator(mode="after")
    def require_filter(self) -> NetworkFilter:
        if self.method is None and self.path_contains is None and self.status is None and self.body_contains is None:
            raise AgentQAValidationError(
                [field_error(("network",), ErrorCode.INPUT_INVALID, "Network filter cần ít nhất một điều kiện")]
            )
        return self


class DownloadExpectation(StrictModel):
    filename_contains: str | None = None
    media_type: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    minimum_count: int = 1


class MaskBox(StrictModel):
    x: int
    y: int
    width: int
    height: int


class VisualExpectation(StrictModel):
    baseline_ref: str
    profile_version: str = "visual/1"
    max_diff_ratio: float
    masks: list[MaskBox] = []
    viewport: dict[str, int] | None = None

    @model_validator(mode="after")
    def validate_ratio(self) -> VisualExpectation:
        if not 0.0 <= self.max_diff_ratio <= 1.0:
            raise AgentQAValidationError(
                [field_error(("visual", "max_diff_ratio"), ErrorCode.INPUT_INVALID, "max_diff_ratio ngoài [0, 1]")]
            )
        return self


class AssertionSpec(StrictModel):
    id: str
    checkpoint_id: str | None = None
    target: TargetDescriptor | None = None
    comparator: Comparator
    expected: ValueExpr | None = None
    required: bool = True
    source_refs: list[str] = []
    wait: WaitPolicy | None = None
    evidence: EvidenceRequirement = EvidenceRequirement.REQUIRED
    network: NetworkFilter | None = None
    download: DownloadExpectation | None = None
    visual: VisualExpectation | None = None


class AssertionResult(StrictModel):
    run_id: UUID
    execution_id: UUID
    step_id: str
    assertion_id: str
    status: AssertionStatus
    expected_redacted: str | None = None
    observed_redacted: str | None = None
    evidence_status: EvidenceStatus
    applicable: bool = True
    reason: str | None = None


class CheckpointEvaluationRequest(StrictModel):
    run_id: UUID
    execution_id: UUID
    step_id: str
    checkpoint_id: str
    assertions: list[AssertionSpec]
    observation: Observation
