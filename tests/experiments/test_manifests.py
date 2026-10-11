from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentqa.contracts.errors import AgentQAValidationError
from agentqa.platform.experiments import ExperimentManifest, validate_manifest
from tests.experiments.conftest import minimal_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
RQ_DIR = REPO_ROOT / "benchmarks" / "experiments"


def load_rq(name: str) -> ExperimentManifest:
    return ExperimentManifest.model_validate(yaml.safe_load((RQ_DIR / f"{name}.yaml").read_text(encoding="utf-8")))


def test_rq_manifests_validate_with_expected_compatibilities() -> None:
    rq1 = load_rq("rq1")
    rq1_flags = validate_manifest(rq1)
    assert {flag.code for flag in rq1_flags} == {"image_capability_unverified"}
    assert all(flag.blocking is False for flag in rq1_flags)

    for name in ("rq2", "rq3"):
        manifest = load_rq(name)
        assert validate_manifest(manifest) == []


def test_manifest_digest_is_stable_and_content_sensitive() -> None:
    content = minimal_manifest()
    first = ExperimentManifest.model_validate(content)
    second = ExperimentManifest.model_validate(content)
    assert first.digest() == second.digest()
    assert len(first.digest()) == 64
    altered = minimal_manifest()
    altered["version"] = "2"
    assert ExperimentManifest.model_validate(altered).digest() != first.digest()


def test_cascade_with_vision_first_is_rejected_at_schema_level() -> None:
    content = minimal_manifest(
        arms=[{"arm_id": "bad", "mode": "agent", "policy": "jev_cascade", "observation": "vision_first"}]
    )
    with pytest.raises(AgentQAValidationError):
        ExperimentManifest.model_validate(content)


def test_rq_arm_counts_are_enforced() -> None:
    content = minimal_manifest(research_question="rq2")
    content["arms"] = content["arms"][:2]
    flags = validate_manifest(ExperimentManifest.model_validate(content))
    assert any(flag.code == "rq2_arms" for flag in flags)


def test_rq1_requires_both_observations() -> None:
    content = minimal_manifest(research_question="rq1")
    content["arms"] = [{"arm_id": "agent_llm_hybrid", "mode": "agent", "policy": "llm", "observation": "hybrid"}]
    flags = validate_manifest(ExperimentManifest.model_validate(content))
    assert {flag.code for flag in flags} == {"rq1_observations"}


def test_budgets_must_be_positive() -> None:
    content = minimal_manifest()
    content["budgets"] = {"max_calls": 0, "max_cost_usd": 1.0}
    with pytest.raises(AgentQAValidationError):
        ExperimentManifest.model_validate(content)


def test_rq2_has_four_arms_and_variant_tokens() -> None:
    rq2 = load_rq("rq2")
    assert len(rq2.arms) == 4
    assert rq2.variant_tokens
    token = rq2.variant_tokens["taskboard_delete_item_healed"][0]
    token_path = REPO_ROOT / "benchmarks" / "public" / "variant-tokens" / "taskboard" / f"{token}.json"
    assert token_path.is_file()


def test_rq3_has_five_arms_with_static_baseline_plan() -> None:
    rq3 = load_rq("rq3")
    assert len(rq3.arms) == 5
    baseline = next(arm for arm in rq3.arms if arm.baseline)
    assert baseline.plan_ref is not None
    assert (REPO_ROOT / baseline.plan_ref).is_file()
    assert rq3.samples.repetitions == 2
