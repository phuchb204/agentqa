from __future__ import annotations

from pathlib import Path

import yaml

from agentqa.platform.experiments import ExperimentManifest, validate_manifest
from tests.experiments.conftest import minimal_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
RQ_DIR = REPO_ROOT / "benchmarks" / "experiments"


def load_rq(name: str) -> ExperimentManifest:
    return ExperimentManifest.model_validate(yaml.safe_load((RQ_DIR / f"{name}.yaml").read_text(encoding="utf-8")))


def test_rq1_arms_share_model_and_parameters_with_cache_bypass_facts() -> None:
    rq1 = load_rq("rq1")
    assert rq1.budgets.routes["opencode_go"] == "deepseek-v4.1-flash"
    assert rq1.budgets.routes["opencode_zen"] == "jev-1.13-free"
    assert rq1.cache.bypass_local is True
    assert rq1.cache.record_provider_cache is True
    observations = {arm.observation for arm in rq1.arms}
    assert observations == {"hybrid", "vision_first"}
    assert {arm.policy for arm in rq1.arms} == {"llm"}
    assert rq1.samples.non_inferiority_margin == 0.05


def test_rq2_four_arms_with_cohorts_and_healing() -> None:
    rq2 = load_rq("rq2")
    assert {arm.arm_id for arm in rq2.arms} == {
        "strict_replay",
        "healing_go_llm",
        "heuristic_ranker",
        "jev_cascade",
    }
    healing_arms = [arm for arm in rq2.arms if arm.healing]
    assert len(healing_arms) == 3
    cohorts = {cohort for arm in rq2.arms for cohort in arm.cohorts}
    assert {"robustness", "fragility"} <= cohorts


def test_rq3_five_arms_with_accounting_phases_and_repetitions() -> None:
    rq3 = load_rq("rq3")
    assert {arm.arm_id for arm in rq3.arms} == {
        "static_baseline",
        "llm_agent",
        "cascade_agent",
        "strict_replay",
        "healing_replay",
    }
    assert rq3.samples.repetitions == 2
    assert "wall_time_seconds" in rq3.analysis.primary_endpoints


def test_arm_gate_profile_defaults_strict_and_accepts_allow_healing() -> None:
    content = minimal_manifest(
        research_question="rq1",
        arms=[
            {"arm_id": "agent_llm_hybrid", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {
                "arm_id": "agent_llm_vision_first",
                "mode": "agent",
                "policy": "llm",
                "observation": "vision_first",
                "gate_profile": "allow_healing",
            },
        ],
    )
    manifest = ExperimentManifest.model_validate(content)
    assert manifest.arms[0].gate_profile == "strict"
    assert manifest.arms[1].gate_profile == "allow_healing"


def test_unsupported_image_is_blocked_not_silently_accepted() -> None:
    content = minimal_manifest(
        research_question="rq1",
        arms=[
            {"arm_id": "agent_llm_hybrid", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {"arm_id": "agent_llm_vision_first", "mode": "agent", "policy": "llm", "observation": "vision_first"},
        ],
    )
    flags = validate_manifest(ExperimentManifest.model_validate(content))
    assert [flag.code for flag in flags] == ["image_capability_unverified"]
    assert flags[0].blocking is False
    assert "vision_first" in flags[0].detail


def test_rq1_with_image_capability_receipt_has_no_flags() -> None:
    content = minimal_manifest(
        research_question="rq1",
        arms=[
            {"arm_id": "agent_llm_hybrid", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {"arm_id": "agent_llm_vision_first", "mode": "agent", "policy": "llm", "observation": "vision_first"},
        ],
        capability_receipts=["artifacts/conformance/image-capability.json"],
    )
    assert validate_manifest(ExperimentManifest.model_validate(content)) == []


def test_no_inferred_ground_truth_in_manifest_schema() -> None:
    manifest = load_rq("rq2")
    dumped = manifest.model_dump(mode="json")
    for key in ("expected", "ground_truth", "oracle_map", "labels"):
        assert key not in dumped
    assert "variant_tokens" in dumped
