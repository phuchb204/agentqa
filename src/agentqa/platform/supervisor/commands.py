from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from agentqa.contracts.actions import Operation
from agentqa.contracts.values import StrictModel


class CommandState(StrEnum):
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    DISPATCHED = "dispatched"
    SETTLED = "settled"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


TERMINAL_COMMAND_STATES = frozenset({CommandState.SETTLED, CommandState.UNKNOWN, CommandState.REJECTED})


class CommandRequest(StrictModel):
    command_id: UUID
    session_key: str
    run_id: UUID
    attempt_id: UUID
    fence_epoch: int
    control_revision: int = 0
    expected_observation_version: int = 0
    operation: Operation
    payload: dict[str, Any] = Field(default_factory=dict)
    side_effect: str = "unknown"


@dataclass(frozen=True)
class CommandReceiptRecord:
    command_id: UUID
    session_id: UUID | None
    state: str
    outcome: str
    fence_epoch: int
    input_digest: str
    evidence: list[str] = field(default_factory=list)
    reason: str | None = None
    recorded_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "command_id": str(self.command_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "state": self.state,
            "outcome": self.outcome,
            "fence_epoch": self.fence_epoch,
            "input_digest": self.input_digest,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }
