from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentqa.platform.calibration import (
    CalibrationManifest,
    CalibrationService,
    CalibrationSplitError,
    CalibrationTrial,
    SuiteCalibrationRunner,
    TrialLabels,
    assert_calibration_only,
    run_calibration,
)
from agentqa.platform.calibration.models import Budgets, QualityPolicy, SearchSpace
from agentqa.platform.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "benchmarks" / "calibration" / "manifest.yaml"


def manifest(
    *,
    calibration: list[str] | None = None,
    pilot: list[str] | None = None,
    evaluation: list[str] | None = None,
    ordering: list[str] | None = None,
) -> CalibrationManifest:
    return CalibrationManifest(
        profile_id="test-profile",
        version="1",
        feature_schema="healing-features/1",
        question_set="healing-questions/1",
        splits={
            "calibration": calibration or ["family-a:case-1", "family-b:case-2"],
            "pilot": pilot or [],
            "evaluation": evaluation or ["family-eval:case-9"],
        },
        search_space=SearchSpace(rankers=["heuristic"], min_score=[0.5], margin_min=[0.1], max_candidates=[24]),
        quality_policy=QualityPolicy(
            max_false_heal_rate=0.01,
            confidence=0.95,
            ordering=ordering or ["false_heal_rate", "refusal_efficiency", "correct_heal_efficiency"],
        ),
        budgets=Budgets(
            max_calls=50,
            max_cost_usd=1.0,
            routes={"opencode_go": "deepseek-v4.1-flash", "opencode_zen": "jev-1.13-free"},
        ),
    )


class ScriptedRunner:
    def __init__(self, plan) -> None:
        self.plan = plan
        self.calls: list[tuple[str, str, str]] = []

    async def run_trial(self, *, candidate, case_key, family, split):
        self.calls.append((candidate.candidate_id, case_key, split))
        value = (
            self.plan(candidate.candidate_id, case_key)
            if callable(self.plan)
            else self.plan[(candidate.candidate_id, case_key)]
        )
        if isinstance(value, TrialLabels):
            return value
        return TrialLabels(**value)


def test_repo_manifest_validates_and_cli_validate_status(tmp_path) -> None:
    assert cli_main(["--json", "calibration", "validate", "--manifest", str(MANIFEST_PATH)]) == 0
    assert (
        cli_main(["--json", "calibration", "status", "--manifest", str(MANIFEST_PATH), "--receipt-dir", str(tmp_path)])
        == 0
    )
    service = CalibrationService(
        CalibrationManifest.model_validate(yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))),
        receipt_dir=tmp_path,
    )
    status = service.status()
    assert status["status"] == "provisional"
    assert status["reason"] == "missing_receipt"
    assert status["production_ready"] is False


def test_cli_execute_without_live_is_rejected() -> None:
    assert cli_main(["--json", "calibration", "execute", "--manifest", str(MANIFEST_PATH)]) == 64


def test_search_uses_only_calibration_split() -> None:
    config = manifest()
    runner = ScriptedRunner(lambda candidate_id, case_key: {"correct_heal": True})
    import asyncio

    outcome = asyncio.run(run_calibration(config, runner))
    splits = {split for _candidate, _case, split in runner.calls}
    assert splits == {"calibration"}
    called_cases = {case for _candidate, case, _split in runner.calls}
    assert "family-eval:case-9" not in called_cases
    assert outcome["receipt"].evidence == "synthetic_test" or outcome["receipt"].sample_units == 2


def test_assert_calibration_only_rejects_evaluation_trials() -> None:
    trials = [
        CalibrationTrial(
            candidate_id="c1",
            case_key="family-eval:case-9",
            family="family-eval",
            split="evaluation",
            labels=TrialLabels(correct_heal=True),
        )
    ]
    with pytest.raises(CalibrationSplitError):
        assert_calibration_only(trials)


def test_ranking_prefers_lower_false_heal_rate() -> None:
    import asyncio

    from agentqa.platform.calibration import CandidateResult

    config = manifest()
    candidates = [
        CandidateResult(candidate_id="risky", ranker="heuristic", params={"min_score": 0.5}),
        CandidateResult(candidate_id="safe", ranker="heuristic", params={"min_score": 0.6}),
    ]

    def plan(candidate_id: str, case_key: str):
        if candidate_id == "risky" and case_key.startswith("family-a"):
            return {"false_heal": True}
        return {"correct_heal": True}

    outcome = asyncio.run(run_calibration(config, ScriptedRunner(plan), candidates=candidates))
    assert outcome["ranking"][0]["candidate_id"] == "safe"
    receipt = outcome["receipt"]
    assert receipt.status == "provisional"
    assert receipt.reason == "bound_exceeds_ceiling"
    assert receipt.bound_upper is not None and receipt.bound_upper > 0.01


def test_synthetic_receipt_stays_provisional(tmp_path) -> None:
    import asyncio

    config = manifest(calibration=[f"family-a:case-{index}" for index in range(300)])
    runner = ScriptedRunner(lambda candidate_id, case_key: {"correct_heal": True, "synthetic": True})
    service = CalibrationService(config, receipt_dir=tmp_path)
    receipt = asyncio.run(service.execute(runner))
    assert receipt.evidence == "synthetic_test"
    assert receipt.status == "provisional"
    assert receipt.reason == "synthetic_evidence"
    status = service.status()
    assert status["production_ready"] is False


def test_measured_ready_profile_requires_bound_groups_and_units(tmp_path) -> None:
    import asyncio

    cases = [f"family-{index}:case-1" for index in range(300)]
    config = manifest(calibration=cases)
    runner = ScriptedRunner(lambda candidate_id, case_key: {"correct_heal": True})
    service = CalibrationService(config, receipt_dir=tmp_path)
    receipt = asyncio.run(service.execute(runner))
    assert receipt.sample_units == 300
    assert receipt.groups == 300
    assert receipt.bound_upper is not None and receipt.bound_upper <= 0.01
    assert receipt.status == "ready"
    status = service.status()
    assert status["status"] == "ready"
    assert status["production_ready"] is True
    assert status["receipt_path"] is not None


def test_single_family_blocks_ready_status() -> None:
    import asyncio

    config = manifest(calibration=[f"family-a:case-{index}" for index in range(300)])
    runner = ScriptedRunner(lambda candidate_id, case_key: {"correct_heal": True})
    outcome = asyncio.run(run_calibration(config, runner))
    receipt = outcome["receipt"]
    assert receipt.status == "provisional"
    assert receipt.reason == "insufficient_independent_groups"


def test_sample_size_report_uses_pilot_when_available() -> None:
    import asyncio

    config = manifest(pilot=["family-pilot:case-1"])
    runner = ScriptedRunner(lambda candidate_id, case_key: {"correct_heal": True})
    outcome = asyncio.run(run_calibration(config, runner))
    sample_size = outcome["receipt"].sample_size
    assert sample_size is not None
    assert sample_size["method"] == "pilot_variance"
    pilot_calls = [call for call in runner.calls if call[2] == "pilot"]
    assert pilot_calls and all(call[1] == "family-pilot:case-1" for call in pilot_calls)


def test_suite_runner_seam_uses_submit_wait_derive() -> None:
    import asyncio

    from agentqa.platform.calibration import CandidateResult

    events: list[str] = []

    async def submit_run(candidate, case_key):
        events.append(f"submit:{candidate.candidate_id}:{case_key}")
        return "run-1"

    async def wait_run(run_id):
        events.append(f"wait:{run_id}")
        return {"verdict": "passed"}

    def derive_labels(summary):
        events.append("derive")
        return TrialLabels(correct_heal=summary["verdict"] == "passed")

    runner = SuiteCalibrationRunner(submit_run=submit_run, wait_run=wait_run, derive_labels=derive_labels)
    labels = asyncio.run(
        runner.run_trial(
            candidate=CandidateResult(candidate_id="c1", ranker="heuristic", params={}),
            case_key="family-a:case-1",
            family="family-a",
            split="calibration",
        )
    )
    assert labels.correct_heal is True
    assert events == ["submit:c1:family-a:case-1", "wait:run-1", "derive"]
