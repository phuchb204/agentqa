from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from agentqa.contracts.runs import TERMINAL_STATUSES, ExecutionStatus, RunResult, Verdict
from agentqa.contracts.verification import AssertionResult, AssertionStatus, EvidenceStatus
from agentqa.verify.completion import CompletionOutcome


@dataclass(frozen=True)
class AttemptEvidence:
    attempt_no: int
    execution_status: ExecutionStatus
    results: tuple[AssertionResult, ...] = ()
    completion: CompletionOutcome | None = None
    applicable: Mapping[str, bool] = field(default_factory=dict)
    recovered: bool = False
    degraded: bool = False
    provisional: bool = False
    revision_ready: bool = True


def reduce_verdict(
    run_id: UUID,
    attempts: list[AttemptEvidence],
    *,
    required_assertions: tuple[str, ...],
) -> RunResult:
    if not attempts:
        raise ValueError("reduce_verdict cần ít nhất một attempt")
    final = attempts[-1]
    if final.execution_status not in TERMINAL_STATUSES:
        return RunResult(run_id=run_id, status=final.execution_status, verdict=None)

    scan = _scan_attempts(attempts)
    proven_failure = _proven_business_failure(scan, required_assertions)
    annotations = _annotations(final, attempts)
    if proven_failure is not None:
        return RunResult(
            run_id=run_id,
            status=final.execution_status,
            verdict=Verdict.FAILED,
            annotations=[*annotations, "business_failure"],
            completion_proof=scan.completion.completion_proof if scan.completion else None,
            required_assertions=_summary(scan, required_assertions),
            reasons=[f"failed_assertion:{proven_failure}"],
        )

    missing = tuple(
        assertion
        for assertion in required_assertions
        if _applicable(scan, assertion) and not _has_result(scan, assertion)
    )
    errors = tuple(
        assertion
        for assertion in required_assertions
        if _applicable(scan, assertion) and _status_of(scan, assertion) == AssertionStatus.ERROR
    )
    unproven_failures = tuple(
        assertion
        for assertion in required_assertions
        if _applicable(scan, assertion) and _failed_without_evidence(scan, assertion)
    )
    inconclusive_reasons: list[str] = []
    if not required_assertions:
        inconclusive_reasons.append("empty_required_assertions")
    if missing:
        inconclusive_reasons.append("missing_required_assertions")
    if errors:
        inconclusive_reasons.append("verification_errors")
    if unproven_failures:
        inconclusive_reasons.append("failure_without_evidence")
    if scan.completion is None or not scan.completion.proof_valid:
        inconclusive_reasons.append("completion_proof_missing")
    if final.execution_status in (ExecutionStatus.CANCELLED, ExecutionStatus.ERROR, ExecutionStatus.FAILED):
        inconclusive_reasons.append(f"terminal_{final.execution_status.value}")
    if inconclusive_reasons:
        return RunResult(
            run_id=run_id,
            status=final.execution_status,
            verdict=Verdict.INCONCLUSIVE,
            annotations=[*annotations, "inconclusive"],
            completion_proof=scan.completion.completion_proof if scan.completion else None,
            required_assertions=_summary(scan, required_assertions),
            reasons=inconclusive_reasons,
        )

    if not final.revision_ready:
        return RunResult(
            run_id=run_id,
            status=final.execution_status,
            verdict=Verdict.INCONCLUSIVE,
            annotations=[*annotations, "inconclusive"],
            completion_proof=scan.completion.completion_proof if scan.completion else None,
            required_assertions=_summary(scan, required_assertions),
            reasons=["revision_not_ready"],
        )
    return RunResult(
        run_id=run_id,
        status=final.execution_status,
        verdict=Verdict.PASSED,
        annotations=annotations,
        completion_proof=scan.completion.completion_proof if scan.completion else None,
        required_assertions=_summary(scan, required_assertions),
        reasons=[],
    )


def _scan_attempts(attempts: list[AttemptEvidence]) -> AttemptEvidence:
    for attempt in reversed(attempts):
        if attempt.completion is not None and attempt.completion.proof_valid:
            return attempt
    return attempts[-1]


def _proven_business_failure(scan: AttemptEvidence, required_assertions: tuple[str, ...]) -> str | None:
    for result in scan.results:
        if result.assertion_id not in required_assertions:
            continue
        if not scan.applicable.get(result.assertion_id, True):
            continue
        if result.status == AssertionStatus.FAILED and result.evidence_status == EvidenceStatus.PRESENT:
            return result.assertion_id
    return None


def _applicable(scan: AttemptEvidence, assertion_id: str) -> bool:
    return scan.applicable.get(assertion_id, True)


def _has_result(scan: AttemptEvidence, assertion_id: str) -> bool:
    return any(result.assertion_id == assertion_id for result in scan.results)


def _status_of(scan: AttemptEvidence, assertion_id: str) -> AssertionStatus | None:
    for result in scan.results:
        if result.assertion_id == assertion_id:
            return result.status
    return None


def _failed_without_evidence(scan: AttemptEvidence, assertion_id: str) -> bool:
    for result in scan.results:
        if result.assertion_id == assertion_id:
            return result.status == AssertionStatus.FAILED and result.evidence_status != EvidenceStatus.PRESENT
    return False


def _summary(scan: AttemptEvidence, required_assertions: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for assertion_id in required_assertions:
        status = _status_of(scan, assertion_id)
        key = status.value if status is not None else AssertionStatus.NOT_EVALUATED.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _annotations(final: AttemptEvidence, attempts: list[AttemptEvidence]) -> list[str]:
    annotations: list[str] = []
    if len(attempts) > 1:
        annotations.append("retried")
    if final.recovered:
        annotations.append("recovered")
    if final.degraded:
        annotations.append("degraded")
    if final.provisional:
        annotations.append("provisional")
    return annotations
