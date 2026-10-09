from __future__ import annotations

from enum import StrEnum
from uuid import UUID

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
    TEXT_EQUALS = "text_equals"
    URL_PATH_EQUALS = "url_path_equals"
    ATTRIBUTE_EQUALS = "attribute_equals"


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
