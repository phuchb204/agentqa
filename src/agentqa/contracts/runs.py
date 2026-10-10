from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from agentqa.contracts.case import CaseContent
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.observation import Modality
from agentqa.contracts.values import StrictModel


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"


class Verdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class GateResult(StrEnum):
    PASSED = "passed"
    REFUSED = "refused"
    ERROR = "error"


class ControlAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.CANCELLED,
        ExecutionStatus.SKIPPED,
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.ERROR,
        ExecutionStatus.INCONCLUSIVE,
    }
)


class RevisionLifecycle(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class RevisionRecord(StrictModel):
    workspace_id: UUID
    entity_id: UUID
    revision_id: UUID
    content: CaseContent
    content_digest: str
    lifecycle: RevisionLifecycle
    author: str
    promoted_by: str | None = None
    promoted_at: datetime | None = None
    supersedes: UUID | None = None


class RunSnapshot(StrictModel):
    snapshot_version: int
    resolved_revision_ids: dict[str, UUID] = {}
    content_digests: list[str] = []
    environment_revision: UUID | None = None
    suite_revision: UUID | None = None
    dataset_revision: UUID | None = None
    fixture_refs: list[str] = []
    parameter_names: list[str] = []
    credential_versions: dict[str, int] = {}
    policy: str
    observation_mode: Modality
    model_routes: list[str] = []
    budgets: dict[str, int] = {}
    cache_profile: str = "default"
    gate_profile: str = "default"
    calibration_ref: str | None = None
    provisional: bool = False
    draft_case: dict | None = None


class StepInstance(StrictModel):
    node_id: str
    path: tuple[str | int, ...] = ()
    dataset_row: int | None = None
    context_key: str
    page_key: str
    frame_key: str | None = None
    execution_id: UUID
    attempt_id: UUID


class RunResult(StrictModel):
    run_id: UUID
    status: ExecutionStatus
    verdict: Verdict | None = None
    annotations: list[str] = []
    completion_proof: str | None = None
    required_assertions: dict[str, int] = {}
    gate: GateResult | None = None
    reasons: list[str] = []

    @model_validator(mode="after")
    def verdict_matches_status(self) -> RunResult:
        if self.status in TERMINAL_STATUSES and self.verdict is None:
            raise AgentQAValidationError(
                [field_error(("verdict",), ErrorCode.INPUT_INVALID, "Run terminal phải có verdict")]
            )
        if self.status not in TERMINAL_STATUSES and self.verdict is not None:
            raise AgentQAValidationError(
                [field_error(("verdict",), ErrorCode.INPUT_INVALID, "Run đang chạy không được có verdict")]
            )
        return self
