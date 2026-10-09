from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue
from agentqa.contracts.verification import (
    AssertionResult,
    AssertionSpec,
    AssertionStatus,
    CheckpointEvaluationRequest,
    Comparator,
    EvidenceRequirement,
    EvidenceStatus,
)

TARGET_REQUIRED = frozenset(
    {
        Comparator.EXISTS,
        Comparator.UNIQUE,
        Comparator.VISIBLE,
        Comparator.COUNT_EQUALS,
        Comparator.COUNT_GREATER_OR_EQUAL,
        Comparator.EQUALS,
        Comparator.NOT_EQUALS,
        Comparator.CONTAINS,
        Comparator.TEXT_EQUALS,
        Comparator.ATTRIBUTE_EQUALS,
    }
)


class SceneFacts(Protocol):
    def url(self) -> str: ...

    def count(self, target: TargetDescriptor) -> int: ...

    def text(self, target: TargetDescriptor) -> str | None: ...

    def value(self, target: TargetDescriptor) -> str | None: ...

    def visible(self, target: TargetDescriptor) -> bool: ...

    def attribute(self, target: TargetDescriptor, name: str) -> str | None: ...

    def evidence_status(self, assertion_id: str) -> EvidenceStatus: ...


@dataclass(frozen=True)
class Outcome:
    status: AssertionStatus
    observed: str | None = None
    reason: str | None = None
    error_code: ErrorCode | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.PRESENT


def evaluate_assertion(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    target = assertion.target
    if target is None and assertion.comparator in TARGET_REQUIRED:
        return _capability()
    expected = _literal(assertion.expected)
    if assertion.expected is not None and expected is None:
        return _capability()
    comparator = assertion.comparator
    if comparator == Comparator.EXISTS:
        if target is None:
            return _capability()
        count = facts.count(target)
        wanted = bool(expected) if expected is not None else True
        return _from_bool((count > 0) == wanted, observed=str(count))
    if comparator == Comparator.UNIQUE:
        if target is None:
            return _capability()
        count = facts.count(target)
        return _from_bool(count == 1, observed=str(count))
    if comparator == Comparator.VISIBLE:
        if target is None:
            return _capability()
        visible = facts.visible(target)
        wanted = bool(expected) if expected is not None else True
        return _from_bool(visible == wanted, observed=str(visible))
    if comparator in (Comparator.COUNT_EQUALS, Comparator.COUNT_GREATER_OR_EQUAL):
        if target is None or not isinstance(expected, int):
            return _capability()
        count = facts.count(target)
        if comparator == Comparator.COUNT_EQUALS:
            return _from_bool(count == expected, observed=str(count))
        return _from_bool(count >= expected, observed=str(count))
    if comparator == Comparator.URL_PATH_EQUALS:
        if not isinstance(expected, str):
            return _capability()
        path = urlsplit(facts.url()).path
        return _from_bool(path == expected, observed=path)
    if comparator == Comparator.ATTRIBUTE_EQUALS:
        if target is None or not target.attributes:
            return _capability()
        name = next(iter(target.attributes))
        actual = facts.attribute(target, name)
        wanted = expected if expected is not None else target.attributes[name]
        return _from_bool(actual == wanted, observed=actual or "")
    if comparator in (Comparator.EQUALS, Comparator.TEXT_EQUALS, Comparator.CONTAINS, Comparator.NOT_EQUALS):
        if target is None:
            return _capability()
        text = facts.text(target)
        if comparator == Comparator.NOT_EQUALS:
            if text is None:
                return Outcome(status=AssertionStatus.PASSED, observed="absent")
            return _from_bool(text.strip() != (expected or ""), observed=text)
        if text is None:
            return _from_bool(False, observed="absent")
        if not isinstance(expected, str):
            return _capability()
        normalized = text.strip()
        if comparator == Comparator.CONTAINS:
            return _from_bool(expected in normalized, observed=normalized)
        return _from_bool(normalized == expected, observed=normalized)
    return _capability()


def evaluate_checkpoint(
    request: CheckpointEvaluationRequest,
    facts: SceneFacts,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[AssertionResult]:
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


def _from_bool(satisfied: bool, *, observed: str | None = None) -> Outcome:
    status = AssertionStatus.PASSED if satisfied else AssertionStatus.FAILED
    return Outcome(status=status, observed=observed)


def _capability() -> Outcome:
    return Outcome(
        status=AssertionStatus.ERROR,
        reason=ErrorCode.CAPABILITY_UNAVAILABLE.value,
        error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
    )


def _literal(value: object) -> object | None:
    if isinstance(value, LiteralValue):
        return value.value
    return None
