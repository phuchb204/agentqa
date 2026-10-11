from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from agentqa.contracts.canonical import digest_content
from agentqa.platform.calibration.models import (
    CRITERIA_VERSION,
    CalibrationManifest,
    CalibrationReceipt,
    CalibrationTrial,
    CandidateResult,
)
from agentqa.platform.statistics.bounds import exact_one_sided


class CalibrationSplitError(ValueError):
    pass


def assert_calibration_only(trials: Sequence[CalibrationTrial]) -> None:
    offenders = sorted({trial.case_key for trial in trials if trial.split != "calibration"})
    if offenders:
        raise CalibrationSplitError(f"search chỉ được dùng calibration split: {offenders}")


def _rates(trials: Sequence[CalibrationTrial]) -> dict[str, float | None]:
    attempts = [trial for trial in trials if not trial.labels.unscorable]
    heal_denominator = [trial for trial in attempts if trial.labels.correct_heal or trial.labels.false_heal]
    refusal_denominator = [trial for trial in attempts if trial.labels.refusal or trial.labels.false_heal]
    false_heals = sum(1 for trial in attempts if trial.labels.false_heal)
    return {
        "false_heal_rate": false_heals / len(attempts) if attempts else None,
        "refusal_efficiency": (
            sum(1 for trial in refusal_denominator if trial.labels.refusal) / len(refusal_denominator)
            if refusal_denominator
            else None
        ),
        "correct_heal_efficiency": (
            sum(1 for trial in heal_denominator if trial.labels.correct_heal) / len(heal_denominator)
            if heal_denominator
            else None
        ),
        "unscorable_rate": (sum(1 for trial in trials if trial.labels.unscorable) / len(trials) if trials else None),
    }


def rank_candidates(
    candidates: Sequence[CandidateResult],
    trials: Sequence[CalibrationTrial],
    manifest: CalibrationManifest,
) -> list[dict]:
    assert_calibration_only(trials)
    ordering = manifest.quality_policy.ordering
    rows: list[dict] = []
    for candidate in candidates:
        candidate_trials = [trial for trial in trials if trial.candidate_id == candidate.candidate_id]
        rates = _rates(candidate_trials)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "ranker": candidate.ranker,
                "params": dict(candidate.params),
                "trials": len(candidate_trials),
                **rates,
            }
        )
    for name in reversed(ordering):
        if name == "false_heal_rate":
            rows.sort(key=lambda row: (row.get(name) is None, row.get(name) or 0.0))
        else:
            rows.sort(key=lambda row: (row.get(name) is None, -(row.get(name) or 0.0)))
    return rows


def _selection_units(trials: Sequence[CalibrationTrial]) -> tuple[int, int, int]:
    by_family: dict[str, CalibrationTrial] = {}
    unscorable = 0
    for trial in sorted(trials, key=lambda item: (item.family, item.case_key)):
        if trial.family in by_family:
            continue
        if trial.labels.unscorable:
            unscorable += 1
            by_family[trial.family] = trial
            continue
        by_family[trial.family] = trial
    units = [trial for trial in by_family.values() if not trial.labels.unscorable]
    errors = sum(1 for trial in units if trial.labels.false_heal)
    return errors, len(units), unscorable


def build_receipt(
    manifest: CalibrationManifest,
    candidate: CandidateResult,
    trials: Sequence[CalibrationTrial],
    *,
    ranking: list[dict] | None = None,
    sample_size: dict | None = None,
) -> CalibrationReceipt:
    candidate_trials = [
        trial for trial in trials if trial.candidate_id == candidate.candidate_id and trial.split == "calibration"
    ]
    assert_calibration_only(candidate_trials)
    errors, units, unscorable = _selection_units(candidate_trials)
    bound = exact_one_sided(errors, units, confidence=manifest.quality_policy.confidence)
    refusal_denominator = [trial for trial in candidate_trials if trial.labels.refusal or trial.labels.false_heal]
    refusal_coverage = (
        sum(1 for trial in refusal_denominator if trial.labels.refusal) / len(refusal_denominator)
        if refusal_denominator
        else None
    )
    synthetic = any(trial.labels.synthetic for trial in candidate_trials)
    profile_digest = digest_content({"candidate": candidate.model_dump(mode="json"), "criteria": CRITERIA_VERSION})
    status = "provisional"
    reason: str | None = None
    if synthetic:
        reason = "synthetic_evidence"
    elif units == 0:
        reason = "missing_units"
    elif len({trial.family for trial in candidate_trials if not trial.labels.unscorable}) < 2:
        reason = "insufficient_independent_groups"
    elif bound.upper is None:
        reason = "missing_bound"
    elif bound.upper > manifest.quality_policy.max_false_heal_rate:
        reason = "bound_exceeds_ceiling"
    else:
        status = "ready"
    return CalibrationReceipt(
        profile_id=manifest.profile_id,
        version=manifest.version,
        evidence="synthetic_test" if synthetic else "measured",
        sample_units=units,
        groups=len({trial.family for trial in candidate_trials}),
        bound_upper=bound.upper,
        bound_method=bound.method,
        confidence=bound.confidence,
        refusal_coverage=refusal_coverage,
        criteria_version=CRITERIA_VERSION,
        profile_digest=profile_digest,
        manifest_digest=manifest.digest(),
        generated_at=datetime.now(UTC),
        status=status,
        reason=reason,
        ranking=ranking or [],
        sample_size=sample_size,
        unscorable_units=unscorable,
    )


def evaluate_candidate(manifest: CalibrationManifest, candidate: CandidateResult) -> dict:
    return {
        "ranker": candidate.ranker,
        "params": dict(candidate.params),
        "min_score": candidate.params.get("min_score"),
        "margin_min": candidate.params.get("margin_min"),
        "max_candidates": candidate.params.get("max_candidates"),
    }
