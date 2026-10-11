from __future__ import annotations

from agentqa.platform.evaluation import (
    EvaluationInput,
    OracleRecord,
    TaskOutcome,
    VariantClassification,
    score,
    success_bounds,
)

EFFECTS = [{"kind": "counter_equals", "counter": "item_created", "value": 1}]


def oracle(effects: list[dict] | None = None) -> OracleRecord:
    return OracleRecord(
        case_key="case",
        app="taskboard",
        fixture_ref="taskboard@1",
        classification=VariantClassification.BENIGN,
        expected_effects=EFFECTS if effects is None else effects,
    )


def test_empty_denominator_is_not_applicable() -> None:
    result = score(
        EvaluationInput(run_id="run", execution_status="succeeded", namespace="ns", probe={"counters": {}}),
        oracle(effects=[]),
    )
    assert result.task_outcome == TaskOutcome.UNSCORABLE
    assert result.unscorable_reason == "no_oracle_effects"
    assert result.counters["opportunities_not_applicable"] == 1
    assert result.counters["attempts_not_applicable"] == 1


def test_valid_blocked_slot_stays_in_task_success_denominator() -> None:
    result = score(
        EvaluationInput(
            run_id="run",
            execution_status="blocked",
            namespace="ns",
            probe={"counters": {"item_created": 1}},
            product_verdict=None,
            product_gate=None,
        ),
        oracle(),
    )
    assert result.counters["valid_scheduled"] == 1
    assert result.counters["known_true"] == 1
    assert result.success_lower_bound == 1.0
    assert result.success_upper_bound == 1.0


def test_unscorable_reports_lower_and_upper_bounds() -> None:
    result = score(
        EvaluationInput(run_id="run", execution_status="succeeded", namespace="ns", probe=None, probe_missing=True),
        oracle(),
    )
    assert result.task_outcome == TaskOutcome.UNSCORABLE
    assert result.scorable is False
    assert result.unscorable_reason == "missing_probe"
    assert result.success_lower_bound == 0.0
    assert result.success_upper_bound == 1.0
    assert result.counters["unscorable"] == 1


def test_provider_error_can_still_succeed_by_independent_oracle() -> None:
    result = score(
        EvaluationInput(
            run_id="run",
            execution_status="error",
            product_verdict=None,
            namespace="ns",
            probe={"counters": {"item_created": 1}},
        ),
        oracle(),
    )
    assert result.task_outcome == TaskOutcome.TRUE
    assert result.counters["valid_scheduled"] == 1
    assert result.product_verdict is None
    assert result.false_pass is False


def test_false_pass_denominator_only_counts_known_false() -> None:
    result = score(
        EvaluationInput(
            run_id="run",
            execution_status="succeeded",
            namespace="ns",
            probe={"counters": {"item_created": 0}},
            product_verdict="passed",
            product_gate="passed",
        ),
        oracle(),
    )
    assert result.task_outcome == TaskOutcome.FALSE
    assert result.false_pass is True
    assert result.counters["known_false"] == 1
    assert result.counters["false_pass_denominator"] == 1


def test_success_bounds_known_vectors() -> None:
    assert success_bounds(0, 0, 10) == (0.0, 0.0, 1.0)
    lower, upper, coverage = success_bounds(7, 3, 10)
    assert (lower, upper, coverage) == (0.7, 1.0, 0.7)
    assert success_bounds(0, 0, 0) == (None, None, None)


def test_zero_event_upper_bound_is_not_zero_via_exact_denominator() -> None:
    lower, upper, _coverage = success_bounds(0, 0, 5)
    assert lower == 0.0
    assert upper == 0.0
    assert upper >= lower
