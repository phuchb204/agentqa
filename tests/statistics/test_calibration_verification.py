from __future__ import annotations

import pytest

from agentqa.contracts.errors import AgentQAValidationError
from agentqa.platform.calibration.live import expand_verification_trials
from agentqa.platform.calibration.models import CalibrationTrial, TrialLabels, VerificationPlan
from agentqa.platform.calibration.profiles import build_verification_receipt


def _plan(**overrides) -> VerificationPlan:
    base: dict = {
        "candidate_id": "heuristic-0.5-0.1-24",
        "ranker": "heuristic",
        "families": ["taskboard-delete", "taskboard-ambiguous"],
        "items_per_family": 3,
        "seeds": [20261010, 20261019],
    }
    base.update(overrides)
    return VerificationPlan(**base)


def _trial(family: str, index: int, *, false_heal: bool = False) -> CalibrationTrial:
    return CalibrationTrial(
        candidate_id="heuristic-0.5-0.1-24",
        case_key=f"{family}:verify-{index:03d}-20261010",
        family=family,
        split="verification",
        labels=TrialLabels(false_heal=false_heal, correct_heal=not false_heal),
    )


def _manifest():
    from agentqa.platform.calibration.models import CalibrationManifest

    return CalibrationManifest(
        profile_id="healing-commandcode-v2",
        version="2",
        feature_schema="healing-features/1",
        question_set="healing-questions/1",
        splits={
            "calibration": ["taskboard-delete:item-1"],
            "evaluation": ["taskboard-delete:item-9"],
        },
        budgets={
            "max_calls": 400,
            "max_cost_usd": 5.0,
            "routes": {"commandcode_chat": "m"},
            "model_pair": "commandcode",
        },
    )


def test_verification_plan_counts_and_validates() -> None:
    plan = _plan()
    assert plan.trial_count() == 2 * 3 * 2
    with pytest.raises(AgentQAValidationError):
        _plan(families=[])
    with pytest.raises(AgentQAValidationError):
        _plan(items_per_family=0)
    with pytest.raises(AgentQAValidationError):
        _plan(seeds=[])


def test_expand_verification_is_deterministic() -> None:
    plan = _plan()
    first = expand_verification_trials(plan)
    second = expand_verification_trials(plan)
    assert first == second
    assert len(first) == plan.trial_count()
    assert len({family for family, _, _ in first}) == 2


def test_verification_receipt_ready_on_300_clean_trials() -> None:
    manifest = _manifest()
    trials = [_trial("taskboard-delete", index) for index in range(150)]
    trials += [_trial("taskboard-ambiguous", index) for index in range(150)]
    receipt = build_verification_receipt(
        manifest,
        __import__("agentqa.platform.calibration.models", fromlist=["CandidateResult"]).CandidateResult(
            candidate_id="heuristic-0.5-0.1-24", ranker="heuristic", params={}
        ),
        trials,
    )
    assert receipt.sample_units == 300
    assert receipt.status == "ready"
    assert receipt.reason is None
    assert receipt.bound_upper is not None and receipt.bound_upper <= 0.01
    assert receipt.criteria_version == "acceptance-refusal-loss-trial/1"


def test_verification_receipt_provisional_on_single_error() -> None:
    manifest = _manifest()
    trials = [_trial("taskboard-delete", index, false_heal=(index == 0)) for index in range(150)]
    trials += [_trial("taskboard-ambiguous", index) for index in range(150)]
    receipt = build_verification_receipt(
        manifest,
        __import__("agentqa.platform.calibration.models", fromlist=["CandidateResult"]).CandidateResult(
            candidate_id="heuristic-0.5-0.1-24", ranker="heuristic", params={}
        ),
        trials,
    )
    assert receipt.status == "provisional"
    assert receipt.reason == "bound_exceeds_ceiling"


def test_verification_receipt_requires_two_groups() -> None:
    manifest = _manifest()
    trials = [_trial("taskboard-delete", index) for index in range(300)]
    receipt = build_verification_receipt(
        manifest,
        __import__("agentqa.platform.calibration.models", fromlist=["CandidateResult"]).CandidateResult(
            candidate_id="heuristic-0.5-0.1-24", ranker="heuristic", params={}
        ),
        trials,
    )
    assert receipt.status == "provisional"
    assert receipt.reason == "insufficient_independent_groups"
