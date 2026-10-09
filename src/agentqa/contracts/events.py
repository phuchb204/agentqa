from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from agentqa.contracts.actions import ActionOutcome
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.models import ModelCallOutcome, ProviderRoute
from agentqa.contracts.runs import ControlAction, ExecutionStatus, Verdict
from agentqa.contracts.values import StrictModel


class EventType(StrEnum):
    RUN_STATE_CHANGED = "run.state_changed"
    CONTROL_REQUESTED = "control.requested"
    CONTROL_EFFECTIVE = "control.effective"
    OBSERVATION_RECORDED = "observation.recorded"
    DECISION_PROPOSED = "decision.proposed"
    MODEL_CALL_STARTED = "model_call.started"
    MODEL_CALL_COMPLETED = "model_call.completed"
    MODEL_CALL_UNKNOWN = "model_call.unknown"
    ACTION_PREPARED = "action.prepared"
    ACTION_ACCEPTED = "action.accepted"
    ACTION_SETTLED = "action.settled"
    CHECKPOINT_EVALUATED = "checkpoint.evaluated"
    HEALING_PROPOSED = "healing.proposed"
    HEALING_ACCEPTED = "healing.accepted"
    HEALING_REFUSED = "healing.refused"
    ARTIFACT_AVAILABLE = "artifact.available"
    ARTIFACT_UNAVAILABLE = "artifact.unavailable"
    RUN_FINALIZED = "run.finalized"


class RunStateChangedPayload(StrictModel):
    event_type: Literal[EventType.RUN_STATE_CHANGED]
    status: ExecutionStatus


class ControlRequestedPayload(StrictModel):
    event_type: Literal[EventType.CONTROL_REQUESTED]
    action: ControlAction
    reason: str | None = None


class ControlEffectivePayload(StrictModel):
    event_type: Literal[EventType.CONTROL_EFFECTIVE]
    action: ControlAction


class ObservationRecordedPayload(StrictModel):
    event_type: Literal[EventType.OBSERVATION_RECORDED]
    observation_id: UUID
    version: int


class DecisionProposedPayload(StrictModel):
    event_type: Literal[EventType.DECISION_PROPOSED]
    decision_type: str


class ModelCallStartedPayload(StrictModel):
    event_type: Literal[EventType.MODEL_CALL_STARTED]
    call_id: UUID
    route: ProviderRoute


class ModelCallCompletedPayload(StrictModel):
    event_type: Literal[EventType.MODEL_CALL_COMPLETED]
    call_id: UUID
    outcome: ModelCallOutcome


class ModelCallUnknownPayload(StrictModel):
    event_type: Literal[EventType.MODEL_CALL_UNKNOWN]
    call_id: UUID


class ActionPreparedPayload(StrictModel):
    event_type: Literal[EventType.ACTION_PREPARED]
    command_id: UUID


class ActionAcceptedPayload(StrictModel):
    event_type: Literal[EventType.ACTION_ACCEPTED]
    command_id: UUID


class ActionSettledPayload(StrictModel):
    event_type: Literal[EventType.ACTION_SETTLED]
    command_id: UUID
    outcome: ActionOutcome


class CheckpointEvaluatedPayload(StrictModel):
    event_type: Literal[EventType.CHECKPOINT_EVALUATED]
    checkpoint_id: str
    passed: int
    failed: int
    errors: int


class HealingProposedPayload(StrictModel):
    event_type: Literal[EventType.HEALING_PROPOSED]
    opportunity_id: str


class HealingAcceptedPayload(StrictModel):
    event_type: Literal[EventType.HEALING_ACCEPTED]
    attempt_id: str


class HealingRefusedPayload(StrictModel):
    event_type: Literal[EventType.HEALING_REFUSED]
    opportunity_id: str
    reason: str


class ArtifactAvailablePayload(StrictModel):
    event_type: Literal[EventType.ARTIFACT_AVAILABLE]
    artifact_id: UUID
    digest: str


class ArtifactUnavailablePayload(StrictModel):
    event_type: Literal[EventType.ARTIFACT_UNAVAILABLE]
    ref: str
    reason: str


class RunFinalizedPayload(StrictModel):
    event_type: Literal[EventType.RUN_FINALIZED]
    status: ExecutionStatus
    verdict: Verdict


EventPayload = Annotated[
    RunStateChangedPayload
    | ControlRequestedPayload
    | ControlEffectivePayload
    | ObservationRecordedPayload
    | DecisionProposedPayload
    | ModelCallStartedPayload
    | ModelCallCompletedPayload
    | ModelCallUnknownPayload
    | ActionPreparedPayload
    | ActionAcceptedPayload
    | ActionSettledPayload
    | CheckpointEvaluatedPayload
    | HealingProposedPayload
    | HealingAcceptedPayload
    | HealingRefusedPayload
    | ArtifactAvailablePayload
    | ArtifactUnavailablePayload
    | RunFinalizedPayload,
    Field(discriminator="event_type"),
]


class RunEvent(StrictModel):
    event_id: UUID
    run_id: UUID
    run_seq: int
    execution_id: UUID | None = None
    execution_seq: int | None = None
    schema_version: Literal["run-event/1"] = "run-event/1"
    type: EventType
    phase: str | None = None
    actor: str
    payload: EventPayload
    recorded_at: datetime

    @field_validator("run_seq")
    @classmethod
    def require_positive_seq(cls, value: int) -> int:
        if value < 1:
            raise AgentQAValidationError([field_error(("run_seq",), ErrorCode.INPUT_INVALID, "run_seq phải >= 1")])
        return value

    @field_validator("recorded_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AgentQAValidationError(
                [field_error(("recorded_at",), ErrorCode.INPUT_INVALID, "Timestamp phải có timezone")]
            )
        return value

    @model_validator(mode="after")
    def payload_matches_type(self) -> RunEvent:
        if self.payload.event_type != self.type:
            raise AgentQAValidationError(
                [field_error(("payload",), ErrorCode.INPUT_INVALID, "payload không khớp event type")]
            )
        if (self.execution_id is None) != (self.execution_seq is None):
            raise AgentQAValidationError(
                [
                    field_error(
                        ("execution_seq",),
                        ErrorCode.INPUT_INVALID,
                        "execution_id và execution_seq phải đi cùng nhau",
                    )
                ]
            )
        return self
