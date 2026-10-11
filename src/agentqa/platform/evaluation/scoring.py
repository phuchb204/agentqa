from __future__ import annotations

from collections import defaultdict

from agentqa.contracts.canonical import digest_content
from agentqa.platform.evaluation.effects import RefResolver, evaluate_effects
from agentqa.platform.evaluation.models import (
    DetectionLabel,
    EvaluationInput,
    EvaluationResult,
    HealingAttempt,
    HealingLabel,
    OpportunityLabel,
    OracleOpportunity,
    OracleRecord,
    TaskOutcome,
)


def target_identity(target: dict | None) -> str | None:
    if not isinstance(target, dict):
        return None
    intent = str(target.get("intent", "")).strip()
    if not intent:
        return None
    name = target.get("name")
    return f"{intent}:{name}" if name else intent


def success_bounds(
    known_true: int, unscorable: int, valid_scheduled: int
) -> tuple[float | None, float | None, float | None]:
    if valid_scheduled <= 0:
        return None, None, None
    lower = known_true / valid_scheduled
    upper = (known_true + unscorable) / valid_scheduled
    coverage = (known_true + (valid_scheduled - known_true - unscorable)) / valid_scheduled
    return lower, upper, coverage


def _attempt_label(
    attempt: HealingAttempt,
    opportunity: OracleOpportunity | None,
    evaluation_input: EvaluationInput,
) -> HealingLabel:
    if attempt.decision == "refused":
        return HealingLabel.REFUSED
    if attempt.decision != "recovered":
        return HealingLabel.UNSCORABLE
    if opportunity is None:
        return HealingLabel.FALSE if attempt.actual_identity is not None else HealingLabel.UNSCORABLE
    if opportunity.kind == "ambiguous_target":
        return HealingLabel.FALSE
    if opportunity.expected_entity is not None:
        if evaluation_input.actual_target_entity is None:
            return HealingLabel.UNSCORABLE
        return (
            HealingLabel.CORRECT
            if evaluation_input.actual_target_entity == opportunity.expected_entity
            else HealingLabel.FALSE
        )
    if attempt.actual_identity is None:
        return HealingLabel.UNSCORABLE
    if opportunity.expected_identity is None:
        return HealingLabel.CORRECT
    return HealingLabel.CORRECT if attempt.actual_identity == opportunity.expected_identity else HealingLabel.FALSE


def _task_outcome(
    evaluation_input: EvaluationInput,
    oracle: OracleRecord,
    ref_resolver: RefResolver | None,
) -> tuple[TaskOutcome, str | None]:
    if not oracle.expected_effects:
        return TaskOutcome.UNSCORABLE, "no_oracle_effects"
    outcome, reason = evaluate_effects(
        oracle.expected_effects,
        app=oracle.app,
        namespace=evaluation_input.namespace,
        probe=evaluation_input.probe,
        parameters=evaluation_input.parameters,
        ref_resolver=ref_resolver,
    )
    if outcome is None:
        return TaskOutcome.UNSCORABLE, reason or "missing_effect_evidence"
    return (TaskOutcome.TRUE if outcome else TaskOutcome.FALSE), None


def score(
    evaluation_input: EvaluationInput,
    oracle: OracleRecord,
    *,
    ref_resolver: RefResolver | None = None,
) -> EvaluationResult:
    task_outcome, unscorable_reason = _task_outcome(evaluation_input, oracle, ref_resolver)
    attempts_by_opportunity: dict[str, list[HealingAttempt]] = defaultdict(list)
    for attempt in evaluation_input.healing_attempts:
        attempts_by_opportunity[attempt.opportunity_id].append(attempt)

    known_opportunities = {opportunity.opportunity_id for opportunity in oracle.opportunities}
    labels: list[OpportunityLabel] = []
    counters: dict[str, int] = {
        "opportunities_total": len(oracle.opportunities),
        "detected": 0,
        "missed": 0,
        "attempts_total": len(evaluation_input.healing_attempts),
        "correct_heals": 0,
        "false_heals": 0,
        "refusals": 0,
        "unscorable_attempts": 0,
    }
    for opportunity in oracle.opportunities:
        attempts = attempts_by_opportunity.get(opportunity.opportunity_id, [])
        detection = DetectionLabel.POSITIVE if attempts else DetectionLabel.MISSED
        counters["detected" if attempts else "missed"] += 1
        healing_labels = [_attempt_label(attempt, opportunity, evaluation_input) for attempt in attempts]
        for label in healing_labels:
            _count_healing(counters, label)
        labels.append(
            OpportunityLabel(
                opportunity_id=opportunity.opportunity_id,
                detection=detection,
                healing=healing_labels,
                actual_identities=[attempt.actual_identity for attempt in attempts],
            )
        )
    for opportunity_id, attempts in attempts_by_opportunity.items():
        if opportunity_id in known_opportunities:
            continue
        healing_labels = [_attempt_label(attempt, None, evaluation_input) for attempt in attempts]
        for label in healing_labels:
            _count_healing(counters, label)
        labels.append(
            OpportunityLabel(
                opportunity_id=opportunity_id,
                detection=DetectionLabel.POSITIVE,
                healing=healing_labels,
                actual_identities=[attempt.actual_identity for attempt in attempts],
            )
        )

    counters["opportunities_not_applicable"] = int(not oracle.opportunities)
    counters["attempts_not_applicable"] = int(not evaluation_input.healing_attempts)
    counters["valid_scheduled"] = 1 if evaluation_input.scheduled else 0
    counters["known_true"] = int(task_outcome == TaskOutcome.TRUE)
    counters["known_false"] = int(task_outcome == TaskOutcome.FALSE)
    counters["unscorable"] = int(task_outcome == TaskOutcome.UNSCORABLE)
    product_passed = evaluation_input.product_verdict == "passed" and evaluation_input.product_gate in ("passed", None)
    counters["product_passed"] = int(product_passed)
    false_pass = product_passed and task_outcome == TaskOutcome.FALSE
    counters["false_passes"] = int(false_pass)
    counters["false_pass_denominator"] = counters["known_false"]

    lower, upper, coverage = success_bounds(counters["known_true"], counters["unscorable"], counters["valid_scheduled"])
    return EvaluationResult(
        input_digest=digest_content(evaluation_input.model_dump(mode="json")),
        oracle_digest=digest_content(oracle.model_dump(mode="json")),
        task_outcome=task_outcome,
        scorable=task_outcome != TaskOutcome.UNSCORABLE,
        unscorable_reason=unscorable_reason,
        product_verdict=evaluation_input.product_verdict,
        product_gate=evaluation_input.product_gate,
        false_pass=false_pass,
        labels=labels,
        counters=counters,
        success_lower_bound=lower,
        success_upper_bound=upper,
        coverage=coverage,
    )


def _count_healing(counters: dict[str, int], label: HealingLabel) -> None:
    if label == HealingLabel.CORRECT:
        counters["correct_heals"] += 1
    elif label == HealingLabel.FALSE:
        counters["false_heals"] += 1
    elif label == HealingLabel.REFUSED:
        counters["refusals"] += 1
    else:
        counters["unscorable_attempts"] += 1
