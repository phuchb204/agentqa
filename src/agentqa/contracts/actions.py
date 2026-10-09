from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import StrictModel, ValueExpr


class Operation(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    FILL = "fill"
    TYPE = "type"
    CLEAR = "clear"
    PRESS = "press"
    CHECK = "check"
    UNCHECK = "uncheck"
    SELECT = "select"
    HOVER = "hover"
    SCROLL = "scroll"
    UPLOAD = "upload"
    WAIT = "wait"
    SWITCH_PAGE = "switch_page"
    SWITCH_FRAME = "switch_frame"
    HANDLE_DIALOG = "handle_dialog"
    EXPECT_DOWNLOAD = "expect_download"

    def needs_target(self) -> bool:
        return self in TARGET_OPERATIONS


TARGET_OPERATIONS = frozenset(
    {
        Operation.CLICK,
        Operation.DOUBLE_CLICK,
        Operation.FILL,
        Operation.TYPE,
        Operation.CLEAR,
        Operation.PRESS,
        Operation.CHECK,
        Operation.UNCHECK,
        Operation.SELECT,
        Operation.HOVER,
        Operation.SCROLL,
        Operation.UPLOAD,
    }
)


class SideEffectClass(StrEnum):
    READ = "read"
    REVERSIBLE = "reversible"
    EXTERNAL_WRITE = "external_write"


class ActionState(StrEnum):
    PROPOSED = "proposed"
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    IMPACTED = "impacted"
    VERIFIED = "verified"


class ActionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ActionProposal(StrictModel):
    proposal_id: UUID
    operation: Operation
    target: TargetDescriptor | None = None
    value: ValueExpr | None = None
    rationale_summary: str
    progress: float | None = None
    stop_requested: bool = False


class ActionCommand(StrictModel):
    command_id: UUID
    run_id: UUID
    attempt_id: UUID
    fence_epoch: int
    expected_observation_version: int
    operation: Operation
    target: TargetDescriptor | None = None
    value: ValueExpr | None = None
    secret_grant_refs: list[str] = []
    postcondition_refs: list[str] = []


class ActionReceipt(StrictModel):
    command_id: UUID
    state: ActionState
    outcome: ActionOutcome
    side_effect: SideEffectClass
    observed_target: TargetDescriptor | None = None
    evidence_refs: list[str] = []
    recorded_at: datetime
