from __future__ import annotations

from uuid import uuid4

import pytest

from agentqa.contracts.runs import ExecutionStatus, GateResult, Verdict
from agentqa.contracts.verification import AssertionResult, AssertionStatus, EvidenceStatus
from agentqa.verify import AttemptEvidence, CompletionOutcome, GateContext, evaluate_gate, exit_code, reduce_verdict

RUN_ID = uuid4()
PROOF_OK = CompletionOutcome(complete=True, proof_valid=True)


def result(
    assertion_id: str,
    status: AssertionStatus,
    *,
    evidence: EvidenceStatus = EvidenceStatus.PRESENT,
) -> AssertionResult:
    return AssertionResult(
        run_id=RUN_ID,
        execution_id=uuid4(),
        step_id="step-1",
        assertion_id=assertion_id,
        status=status,
        evidence_status=evidence,
    )


def attempt(
    *,
    no: int = 1,
    status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    results: tuple[AssertionResult, ...] = (),
    completion: CompletionOutcome | None = PROOF_OK,
    applicable: dict[str, bool] | None = None,
    recovered: bool = False,
    degraded: bool = False,
    provisional: bool = False,
    revision_ready: bool = True,
) -> AttemptEvidence:
    return AttemptEvidence(
        attempt_no=no,
        execution_status=status,
        results=results,
        completion=completion,
        applicable=applicable or {},
        recovered=recovered,
        degraded=degraded,
        provisional=provisional,
        revision_ready=revision_ready,
    )


def test_proven_business_failure_is_failed() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt(results=(result("item_exists_once", AssertionStatus.FAILED),))],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.FAILED
    assert "business_failure" in outcome.annotations
    assert outcome.reasons == ["failed_assertion:item_exists_once"]


def test_empty_required_assertions_not_passed() -> None:
    outcome = reduce_verdict(RUN_ID, [attempt(results=())], required_assertions=())
    assert outcome.verdict == Verdict.INCONCLUSIVE
    assert "empty_required_assertions" in outcome.reasons


def test_skipped_required_checkpoint_is_inconclusive() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt(completion=CompletionOutcome(complete=False, proof_valid=False, missing_receipts=("result",)))],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE
    assert "missing_required_assertions" in outcome.reasons
    assert "completion_proof_missing" in outcome.reasons


def test_wrong_entity_failure_stays_failed() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt(results=(result("item_exists_once", AssertionStatus.FAILED),))],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.FAILED


def test_lost_proof_with_passing_results_is_inconclusive() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                results=(result("item_exists_once", AssertionStatus.PASSED),),
                completion=CompletionOutcome(complete=True, proof_valid=False, missing_receipts=("result",)),
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.INCONCLUSIVE
    assert "completion_proof_missing" in outcome.reasons


def test_failure_retained_despite_later_cleanup_error() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                status=ExecutionStatus.ERROR,
                results=(result("item_exists_once", AssertionStatus.FAILED),),
                completion=CompletionOutcome(complete=True, proof_valid=True),
            )
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.FAILED


def test_full_pass_requires_proof_and_revision_ready() -> None:
    passed = reduce_verdict(
        RUN_ID,
        [attempt(results=(result("item_exists_once", AssertionStatus.PASSED),))],
        required_assertions=("item_exists_once",),
    )
    assert passed.verdict == Verdict.PASSED
    assert passed.required_assertions == {"passed": 1}

    not_ready = reduce_verdict(
        RUN_ID,
        [attempt(results=(result("item_exists_once", AssertionStatus.PASSED),), revision_ready=False)],
        required_assertions=("item_exists_once",),
    )
    assert not_ready.verdict == Verdict.INCONCLUSIVE
    assert "revision_not_ready" in not_ready.reasons


def test_active_run_has_null_verdict() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt(status=ExecutionStatus.RUNNING, results=())],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict is None


def test_recovered_attempt_supersedes_failed_retry() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [
            attempt(
                no=1,
                status=ExecutionStatus.ERROR,
                results=(result("item_exists_once", AssertionStatus.FAILED),),
                completion=CompletionOutcome(complete=False, proof_valid=False),
            ),
            attempt(
                no=2,
                results=(result("item_exists_once", AssertionStatus.PASSED),),
                recovered=True,
            ),
        ],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.PASSED
    assert "retried" in outcome.annotations
    assert "recovered" in outcome.annotations


def test_provisional_pass_is_annotated_and_strict_gate_refuses() -> None:
    outcome = reduce_verdict(
        RUN_ID,
        [attempt(results=(result("item_exists_once", AssertionStatus.PASSED),), provisional=True)],
        required_assertions=("item_exists_once",),
    )
    assert outcome.verdict == Verdict.PASSED
    assert "provisional" in outcome.annotations
    decision = evaluate_gate(
        "strict",
        outcome.verdict,
        GateContext(completed=True, revision_ready=True, evidence_ok=True, provisional=True),
    )
    assert decision.result == GateResult.REFUSED
    assert "provisional_not_allowed" in decision.reasons


@pytest.mark.parametrize(
    ("profile", "context_kwargs", "expected_result", "reason"),
    [
        ("strict", {}, GateResult.PASSED, None),
        (
            "strict",
            {"healed": True, "healing_guards_ok": True},
            GateResult.REFUSED,
            "healed_not_allowed_in_strict",
        ),
        (
            "allow_healing",
            {"healed": True, "healing_guards_ok": True},
            GateResult.PASSED,
            None,
        ),
        (
            "allow_healing",
            {"healed": True, "healing_guards_ok": False},
            GateResult.REFUSED,
            "healing_guards_missing",
        ),
        ("allow_healing", {"degraded": True}, GateResult.REFUSED, "degraded_not_allowed"),
        ("strict", {"evidence_ok": False}, GateResult.REFUSED, "evidence_missing"),
        ("strict", {"completed": False}, GateResult.REFUSED, "execution_incomplete"),
    ],
)
def test_gate_matrix(profile: str, context_kwargs: dict, expected_result: GateResult, reason: str | None) -> None:
    base: dict = {"completed": True, "revision_ready": True, "evidence_ok": True}
    base.update(context_kwargs)
    decision = evaluate_gate(profile, Verdict.PASSED, GateContext(**base))
    assert decision.result == expected_result
    if reason is not None:
        assert reason in decision.reasons
    assert decision.accepted is (expected_result == GateResult.PASSED)


def test_gate_verdict_precedence() -> None:
    assert evaluate_gate("strict", Verdict.INCONCLUSIVE, GateContext(True, True, True)).result == GateResult.REFUSED
    assert evaluate_gate("strict", None, GateContext(True, True, True)).result == GateResult.ERROR
    failed = evaluate_gate("strict", Verdict.FAILED, GateContext(True, True, True))
    assert failed.result == GateResult.REFUSED
    assert failed.business_failure is True


def test_exit_code_precedence() -> None:
    refused = evaluate_gate("strict", Verdict.INCONCLUSIVE, GateContext(True, True, True))
    passed = evaluate_gate("strict", Verdict.PASSED, GateContext(True, True, True))
    failed = evaluate_gate("strict", Verdict.FAILED, GateContext(True, True, True))
    assert exit_code(invalid_pre_submit=True) == 64
    assert exit_code(cancelled=True, invalid_pre_submit=False) == 130
    assert exit_code(business_failed=True, gate_decisions=[failed]) == 1
    assert exit_code(gate_decisions=[refused]) == 2
    assert exit_code(gate_decisions=[passed, passed]) == 0
