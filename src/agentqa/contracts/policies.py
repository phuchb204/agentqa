from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from agentqa.contracts.actions import Operation
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.observation import Modality
from agentqa.contracts.values import StrictModel, ValueExpr


class PolicyKind(StrEnum):
    LLM = "llm"
    JEV_CASCADE = "jev_cascade"


class RunMode(StrEnum):
    AGENT = "agent"
    REPLAY_STRICT = "replay_strict"
    REPLAY_HEALING = "replay_healing"


POLICY_MODALITIES: dict[PolicyKind, frozenset[Modality]] = {
    PolicyKind.LLM: frozenset({Modality.SEMANTIC, Modality.HYBRID, Modality.VISION_FIRST}),
    PolicyKind.JEV_CASCADE: frozenset({Modality.SEMANTIC, Modality.HYBRID}),
}


def validate_mode_policy_modality(mode: RunMode, policy: PolicyKind, modality: Modality) -> None:
    if mode is not RunMode.AGENT:
        return
    allowed = POLICY_MODALITIES.get(policy, frozenset())
    if modality not in allowed:
        raise AgentQAValidationError(
            [
                field_error(
                    ("observation_mode",),
                    ErrorCode.CAPABILITY_MISMATCH,
                    f"Policy '{policy.value}' không hỗ trợ modality '{modality.value}'",
                )
            ]
        )


class PolicyProfile(StrictModel):
    policy: PolicyKind
    version: str
    allow_degradation: bool = False
    confidence_min: float = 0.6
    p_max_min: float = 0.5
    margin_min: float = 0.2
    progress_stop: float = 0.9
    max_steps: int = 24
    stuck_after: int = 3


class AgentProposal(StrictModel):
    proposal_id: UUID
    policy: PolicyKind
    policy_version: str
    plan_version: str
    operation: Operation
    target_intent: str | None = None
    candidate_id: str | None = None
    value: ValueExpr | None = None
    rationale: str = ""
    confidence: float | None = None
    progress: float | None = None
    stop_requested: bool = False

    @model_validator(mode="after")
    def require_identity(self) -> AgentProposal:
        if not self.rationale.strip() and not self.stop_requested:
            raise AgentQAValidationError(
                [field_error(("rationale",), ErrorCode.INPUT_INVALID, "Proposal cần rationale hoặc stop")]
            )
        return self


class ProposalKind(StrEnum):
    ACTION = "action"
    STOP = "stop"
    NEED_CONTEXT = "need_context"
    LOW_CONFIDENCE = "low_confidence"
    MALFORMED = "malformed"
    FAILED = "failed"


class PolicyOutcome(StrictModel):
    kind: ProposalKind
    proposal: AgentProposal | None = None
    reason: str = ""
    detail: str | None = None
    degraded: bool = False
    policy_version: str = ""
    call_group_id: UUID | None = None


class SentinelDecision(StrEnum):
    NONE = "none"
    NEED_MORE_CONTEXT = "need_more_context"


class ChoiceSentinel(StrictModel):
    kind: str = Field(default="sentinel")
    value: SentinelDecision
