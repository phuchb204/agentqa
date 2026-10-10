from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue, ValueExpr
from agentqa.contracts.verification import (
    AssertionResult,
    AssertionSpec,
    AssertionStatus,
    CheckpointEvaluationRequest,
    Comparator,
    EvidenceRequirement,
    EvidenceStatus,
    NetworkFilter,
)


@dataclass(frozen=True)
class NetworkEntry:
    method: str
    url: str
    status: int
    body_digest: str | None = None
    body_excerpt: str | None = None


@dataclass(frozen=True)
class DownloadEntry:
    filename: str
    media_type: str | None
    size_bytes: int | None
    sha256: str | None


class SceneFacts(Protocol):
    def url(self) -> str: ...

    def count(self, target: TargetDescriptor) -> int: ...

    def text(self, target: TargetDescriptor) -> str | None: ...

    def value(self, target: TargetDescriptor) -> str | None: ...

    def visible(self, target: TargetDescriptor) -> bool: ...

    def hidden(self, target: TargetDescriptor) -> bool: ...

    def attribute(self, target: TargetDescriptor, name: str) -> str | None: ...

    def checked(self, target: TargetDescriptor) -> bool | None: ...

    def enabled(self, target: TargetDescriptor) -> bool | None: ...

    def evidence_status(self, assertion_id: str) -> EvidenceStatus: ...

    def capture(self, name: str) -> object | None: ...

    def parameter(self, name: str) -> object | None: ...

    def network(self, filter: NetworkFilter) -> list[NetworkEntry]: ...

    def downloads(self) -> list[DownloadEntry]: ...

    def baseline(self, ref: str) -> bytes | None: ...

    def screenshot(self) -> bytes | None: ...


@dataclass(frozen=True)
class Outcome:
    status: AssertionStatus
    observed: str | None = None
    reason: str | None = None
    error_code: ErrorCode | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.PRESENT


@dataclass(frozen=True)
class EvaluatorTable:
    handlers: dict[Comparator, object] = field(default_factory=dict)


def evaluate_assertion(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    from agentqa.verify.evaluators import download as download_module
    from agentqa.verify.evaluators import elements, entities, network, url, visual

    comparator = assertion.comparator
    if comparator in entities.HANDLED and assertion.target is not None and assertion.target.entity_scope is not None:
        return entities.evaluate(assertion, facts)
    if comparator in elements.HANDLED:
        return elements.evaluate(assertion, facts)
    if comparator in url.HANDLED:
        return url.evaluate(assertion, facts)
    if comparator in network.HANDLED:
        return network.evaluate(assertion, facts)
    if comparator in download_module.HANDLED:
        return download_module.evaluate(assertion, facts)
    if comparator in visual.HANDLED:
        return visual.evaluate(assertion, facts)
    return capability()


def evaluate_checkpoint(
    request: CheckpointEvaluationRequest,
    facts: SceneFacts,
    *,
    clock=None,
    sleep=None,
) -> list[AssertionResult]:
    import time

    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    waiting = [assertion for assertion in request.assertions if assertion.wait is not None]
    outcomes = {assertion.id: _guarded_outcome(assertion, facts) for assertion in request.assertions}
    if waiting:
        timeout = max(assertion.wait.timeout_ms for assertion in waiting if assertion.wait is not None) / 1000
        poll = min(assertion.wait.poll_ms for assertion in waiting if assertion.wait is not None) / 1000
        deadline = clock() + timeout
        while not all(outcomes[assertion.id].status == AssertionStatus.PASSED for assertion in waiting):
            if clock() >= deadline:
                break
            sleep(poll)
            outcomes = {assertion.id: _guarded_outcome(assertion, facts) for assertion in request.assertions}
    return [_to_result(request, assertion, outcomes[assertion.id]) for assertion in request.assertions]


def literal_value(expected: ValueExpr | None) -> object | None:
    return expected.value if isinstance(expected, LiteralValue) else None


def dynamic_value(expected: ValueExpr | None, facts: SceneFacts) -> tuple[object | None, str | None]:
    if expected is None:
        return None, None
    if isinstance(expected, LiteralValue):
        return expected.value, None
    kind = expected.kind
    if kind == "capture":
        value = facts.capture(expected.name)
        if value is None:
            return None, ErrorCode.INVALID_CAPTURE.value
        return value, None
    if kind == "parameter":
        value = facts.parameter(expected.name)
        if value is None:
            return None, ErrorCode.INPUT_INVALID.value
        return value, None
    return None, ErrorCode.CAPABILITY_UNAVAILABLE.value


def from_bool(satisfied: bool, *, observed: str | None = None) -> Outcome:
    status = AssertionStatus.PASSED if satisfied else AssertionStatus.FAILED
    return Outcome(status=status, observed=observed)


def capability(reason: str | None = None) -> Outcome:
    return Outcome(
        status=AssertionStatus.ERROR,
        reason=reason or ErrorCode.CAPABILITY_UNAVAILABLE.value,
        error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
    )


def _guarded_outcome(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    outcome = evaluate_assertion(assertion, facts)
    if outcome.status == AssertionStatus.ERROR:
        return outcome
    evidence_status = facts.evidence_status(assertion.id)
    if evidence_status == EvidenceStatus.REDACTION_FAILED:
        return Outcome(
            status=AssertionStatus.ERROR,
            observed=outcome.observed,
            reason=ErrorCode.EVIDENCE_REDACTION_FAILED.value,
            error_code=ErrorCode.EVIDENCE_REDACTION_FAILED,
            evidence_status=EvidenceStatus.REDACTION_FAILED,
        )
    if assertion.evidence == EvidenceRequirement.REQUIRED and evidence_status != EvidenceStatus.PRESENT:
        return Outcome(
            status=AssertionStatus.ERROR,
            observed=outcome.observed,
            reason=ErrorCode.EVIDENCE_MISSING.value,
            error_code=ErrorCode.EVIDENCE_MISSING,
            evidence_status=EvidenceStatus.MISSING,
        )
    return Outcome(
        status=outcome.status,
        observed=outcome.observed,
        reason=outcome.reason,
        error_code=outcome.error_code,
        evidence_status=evidence_status,
    )


def _to_result(request: CheckpointEvaluationRequest, assertion: AssertionSpec, outcome: Outcome) -> AssertionResult:
    expected_redacted = None
    if isinstance(assertion.expected, LiteralValue):
        expected_redacted = str(assertion.expected.value)
    return AssertionResult(
        run_id=request.run_id,
        execution_id=request.execution_id,
        step_id=request.step_id,
        assertion_id=assertion.id,
        status=outcome.status,
        expected_redacted=expected_redacted,
        observed_redacted=outcome.observed,
        evidence_status=outcome.evidence_status,
        applicable=True,
        reason=outcome.reason,
    )
