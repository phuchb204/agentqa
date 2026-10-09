from __future__ import annotations

from uuid import uuid4

from agentqa.contracts.runs import ExecutionStatus, Verdict
from agentqa.contracts.verification import AssertionResult, AssertionStatus, EvidenceStatus
from agentqa.verify import AttemptEvidence, CompletionOutcome, reduce_verdict

RUN_ID = uuid4()
PROOF_OK = CompletionOutcome(complete=True, proof_valid=True)


def result(
    assertion_id: str,
    status: AssertionStatus,
    *,
    evidence: EvidenceStatus = EvidenceStatus.PRESENT,
    reason: str | None = None,
) -> AssertionResult:
    return AssertionResult(
        run_id=RUN_ID,
        execution_id=uuid4(),
        step_id="step-1",
        assertion_id=assertion_id,
        status=status,
        evidence_status=evidence,
        reason=reason,
    )


def attempt(results: tuple[AssertionResult, ...]) -> AttemptEvidence:
    return AttemptEvidence(
        attempt_no=1,
        execution_status=ExecutionStatus.SUCCEEDED,
        results=results,
        completion=PROOF_OK,
    )


def test_evidence_error_does_not_become_business_failure() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                (
                    result(
                        "item_exists_once",
                        AssertionStatus.ERROR,
                        evidence=EvidenceStatus.MISSING,
                        reason="evidence_missing",
                    ),
                )
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE
    assert "verification_errors" in outcome.reasons


def test_verification_error_reason_is_inconclusive() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt((result("item_exists_once", AssertionStatus.ERROR, reason="verification_error"),))],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE


def test_redaction_failed_is_error_not_failure() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                (
                    result(
                        "item_exists_once",
                        AssertionStatus.ERROR,
                        evidence=EvidenceStatus.REDACTION_FAILED,
                        reason="evidence_redaction_failed",
                    ),
                )
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE
    assert "verification_errors" in outcome.reasons


def test_optional_assertion_error_does_not_block_pass() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                (
                    result("item_exists_once", AssertionStatus.PASSED),
                    result("nice_to_have", AssertionStatus.ERROR, reason="verification_error"),
                )
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.PASSED
    assert outcome.required_assertions == {"passed": 1}


def test_failed_required_assertion_without_evidence_is_inconclusive_not_failed() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                (
                    result(
                        "item_exists_once",
                        AssertionStatus.FAILED,
                        evidence=EvidenceStatus.MISSING,
                    ),
                )
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE
