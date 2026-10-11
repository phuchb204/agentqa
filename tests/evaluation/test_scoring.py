from __future__ import annotations

from agentqa.platform.evaluation import (
    DetectionLabel,
    EvaluationInput,
    HealingAttempt,
    HealingLabel,
    OracleOpportunity,
    OracleRecord,
    TaskOutcome,
    VariantClassification,
    score,
)

EFFECTS = [{"kind": "counter_equals", "counter": "item_created", "value": 1}]
OPPORTUNITY = OracleOpportunity(
    opportunity_id="case:delete:item-1",
    step_id="delete_item",
    original_identity="delete_item:Xoá việc",
    expected_entity="item-1",
    kind="benign_mismatch",
)


def oracle(*, opportunities: list[OracleOpportunity] | None = None, effects: list[dict] | None = None) -> OracleRecord:
    return OracleRecord(
        case_key="case",
        app="taskboard",
        fixture_ref="taskboard@1",
        classification=VariantClassification.BENIGN,
        expected_effects=EFFECTS if effects is None else effects,
        opportunities=opportunities or [],
    )


def evaluation_input(
    *,
    probe: dict | None = None,
    verdict: str | None = "passed",
    gate: str | None = "passed",
    attempts: list[HealingAttempt] | None = None,
    entity: str | None = None,
    status: str = "succeeded",
) -> EvaluationInput:
    return EvaluationInput(
        run_id="run-1",
        execution_status=status,
        product_verdict=verdict,
        product_gate=gate,
        namespace="ns",
        probe=probe if probe is not None else {"counters": {"item_created": 1}},
        probe_missing=probe is None,
        actual_target_entity=entity,
        healing_attempts=attempts or [],
    )


def test_correct_heal_with_passed_product() -> None:
    attempt = HealingAttempt(
        opportunity_id=OPPORTUNITY.opportunity_id,
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity="delete_item:Xoá việc",
    )
    result = score(evaluation_input(attempts=[attempt], entity="item-1"), oracle(opportunities=[OPPORTUNITY]))
    assert result.task_outcome == TaskOutcome.TRUE
    assert result.labels[0].detection == DetectionLabel.POSITIVE
    assert result.labels[0].healing == [HealingLabel.CORRECT]
    assert result.counters["correct_heals"] == 1
    assert result.counters["false_heals"] == 0
    assert result.counters["detected"] == 1
    assert result.false_pass is False


def test_wrong_heal_marks_false_even_when_final_failed() -> None:
    attempt = HealingAttempt(
        opportunity_id=OPPORTUNITY.opportunity_id,
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity="delete_item:Xoá việc",
    )
    result = score(
        evaluation_input(attempts=[attempt], entity="item-2", verdict="failed"),
        oracle(
            opportunities=[OPPORTUNITY], effects=[{"kind": "counter_equals", "counter": "item_deleted", "value": 1}]
        ),
    )
    assert result.labels[0].healing == [HealingLabel.FALSE]
    assert result.counters["false_heals"] == 1
    assert result.task_outcome == TaskOutcome.FALSE
    assert result.false_pass is False


def test_wrong_heal_with_product_passed_is_false_pass() -> None:
    attempt = HealingAttempt(
        opportunity_id=OPPORTUNITY.opportunity_id,
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity="delete_item:Xoá việc",
    )
    result = score(
        evaluation_input(attempts=[attempt], entity="item-2", verdict="passed"),
        oracle(
            opportunities=[OPPORTUNITY], effects=[{"kind": "counter_equals", "counter": "item_deleted", "value": 1}]
        ),
    )
    assert result.task_outcome == TaskOutcome.FALSE
    assert result.false_pass is True
    assert result.counters["false_passes"] == 1
    assert result.counters["false_pass_denominator"] == 1


def test_valid_refusal_is_counted_without_correct_heal() -> None:
    attempt = HealingAttempt(
        opportunity_id=OPPORTUNITY.opportunity_id,
        attempt_ref="attempt-1",
        decision="refused",
        actual_identity=None,
    )
    result = score(evaluation_input(attempts=[attempt], entity=None), oracle(opportunities=[OPPORTUNITY]))
    assert result.labels[0].healing == [HealingLabel.REFUSED]
    assert result.counters["refusals"] == 1
    assert result.counters["correct_heals"] == 0
    assert result.counters["false_heals"] == 0


def test_missed_mismatch_is_detection_missed() -> None:
    result = score(evaluation_input(attempts=[]), oracle(opportunities=[OPPORTUNITY]))
    assert result.labels[0].detection == DetectionLabel.MISSED
    assert result.counters["missed"] == 1
    assert result.counters["detected"] == 0


def test_unchanged_valid_target_has_not_applicable_denominators() -> None:
    result = score(evaluation_input(attempts=[]), oracle(opportunities=[]))
    assert result.counters["opportunities_not_applicable"] == 1
    assert result.counters["attempts_not_applicable"] == 1
    assert result.task_outcome == TaskOutcome.TRUE


def test_missing_actual_target_is_unscorable_not_correct() -> None:
    attempt = HealingAttempt(
        opportunity_id=OPPORTUNITY.opportunity_id,
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity=None,
    )
    result = score(evaluation_input(attempts=[attempt], entity=None), oracle(opportunities=[OPPORTUNITY]))
    assert result.labels[0].healing == [HealingLabel.UNSCORABLE]
    assert result.counters["unscorable_attempts"] == 1
    assert result.counters["correct_heals"] == 0


def test_retries_do_not_add_opportunities() -> None:
    attempts = [
        HealingAttempt(
            opportunity_id=OPPORTUNITY.opportunity_id,
            attempt_ref=f"attempt-{index}",
            decision="recovered",
            actual_identity="delete_item:Xoá việc",
        )
        for index in (1, 2, 3)
    ]
    result = score(evaluation_input(attempts=attempts, entity="item-1"), oracle(opportunities=[OPPORTUNITY]))
    assert result.counters["opportunities_total"] == 1
    assert result.counters["attempts_total"] == 3
    assert result.labels[0].healing == [HealingLabel.CORRECT] * 3
    assert result.counters["correct_heals"] == 3


def test_ambiguous_target_recovery_is_false_heal() -> None:
    ambiguous = OracleOpportunity(
        opportunity_id="case:ambiguous:Việc giống nhau",
        step_id="resolve_entity",
        original_identity="ambiguous:Việc giống nhau",
        kind="ambiguous_target",
    )
    attempt = HealingAttempt(
        opportunity_id=ambiguous.opportunity_id,
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity="delete_item:Xoá việc",
    )
    result = score(evaluation_input(attempts=[attempt]), oracle(opportunities=[ambiguous]))
    assert result.labels[0].healing == [HealingLabel.FALSE]


def test_orphan_recovery_counts_false_heal() -> None:
    attempt = HealingAttempt(
        opportunity_id="not-in-oracle",
        attempt_ref="attempt-1",
        decision="recovered",
        actual_identity="delete_item:Xoá việc",
    )
    result = score(evaluation_input(attempts=[attempt]), oracle(opportunities=[]))
    assert result.counters["false_heals"] == 1
