from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from agentqa.contracts.actions import ActionCommand, ActionReceipt
from agentqa.contracts.artifacts import ArtifactKind, ArtifactMetadata, IntegrityStatus
from agentqa.contracts.case import Condition, FixtureReceipt
from agentqa.contracts.events import RunEvent
from agentqa.contracts.identity import CandidateProof, TargetDescriptor
from agentqa.contracts.models import (
    DecisionRequest,
    DecisionResult,
    GenerationRequest,
    GenerationResult,
    ModelCallRecord,
)
from agentqa.contracts.observation import Modality, Observation, ProbeOutcome
from agentqa.contracts.runs import GateResult, RunResult, Verdict
from agentqa.contracts.values import SensitiveValue
from agentqa.contracts.verification import AssertionResult, CheckpointEvaluationRequest


class ClockPort(Protocol):
    def utc_now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class BrowserReadPort(Protocol):
    def observe(self, context_key: str, mode: Modality) -> Observation: ...

    def probe(self, condition: Condition, context_key: str) -> ProbeOutcome: ...

    def read_download_metadata(self, context_key: str) -> dict[str, str]: ...

    def capture_safe_evidence(self, context_key: str, label: str) -> str: ...


class BrowserActionPort(Protocol):
    def dispatch(self, command: ActionCommand) -> ActionReceipt: ...

    def query_outcome(self, command_id: UUID) -> ActionReceipt: ...


class IdentityPort(Protocol):
    def resolve(self, descriptor: TargetDescriptor, context_key: str) -> list[CandidateProof]: ...

    def rank(self, candidates: list[CandidateProof], descriptor: TargetDescriptor) -> list[CandidateProof]: ...


class VerificationPort(Protocol):
    def evaluate_checkpoint(self, request: CheckpointEvaluationRequest) -> list[AssertionResult]: ...

    def finalize(
        self,
        run_id: UUID,
        execution_id: UUID,
        results: list[AssertionResult],
        completion_proof: str | None,
        gate_profile: str,
    ) -> RunResult: ...

    def evaluate_gate(
        self,
        profile: str,
        verdict: Verdict,
        healed: bool,
        healing_allowed: bool,
    ) -> GateResult: ...


class GenerativeModelPort(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...


class DecisionModelPort(Protocol):
    async def decide(self, request: DecisionRequest) -> DecisionResult: ...


class EventSink(Protocol):
    def append(self, event: RunEvent) -> int: ...


class CallLedgerPort(Protocol):
    def record(self, call: ModelCallRecord) -> UUID: ...


class ArtifactPort(Protocol):
    def put_bytes(self, kind: ArtifactKind, payload: bytes, media_type: str) -> ArtifactMetadata: ...

    def scoped_ref(self, artifact_id: UUID) -> str: ...

    def mark_integrity(self, artifact_id: UUID, status: IntegrityStatus) -> None: ...


class SecretGrantPort(Protocol):
    def issue(self, credential_ref: str, purpose: str, target: TargetDescriptor | None) -> str: ...

    def resolve(self, grant_id: str) -> SensitiveValue: ...


class FixturePort(Protocol):
    def prepare(self, fixture_ref: str, namespace: str) -> FixtureReceipt: ...

    def reset(self, fixture_ref: str, namespace: str) -> FixtureReceipt: ...

    def cleanup(self, fixture_ref: str, namespace: str) -> FixtureReceipt: ...


class BudgetPort(Protocol):
    def reserve(self, resource: str, amount: int) -> str: ...

    def settle(self, reservation_id: str, actual: int) -> None: ...

    def remaining(self, resource: str) -> int: ...
