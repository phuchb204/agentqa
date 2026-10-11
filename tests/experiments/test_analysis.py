from __future__ import annotations

from agentqa.platform.experiments import compute_analysis
from tests.experiments.conftest import manifest_from, minimal_manifest, slot_payload


def base_slots() -> list[dict]:
    return [
        slot_payload(
            arm_id="static_baseline",
            case_key="taskboard_create_item",
            task_outcome="true",
            detected=2,
            missed=1,
            correct_heals=1,
            wall_time=2.0,
        ),
        slot_payload(
            arm_id="llm_agent",
            case_key="taskboard_create_item",
            task_outcome="true",
            detected=3,
            correct_heals=2,
            model_requested="deepseek-v4.1-flash",
            model_resolved=None,
            provider_cache=True,
            cost_basis="price_estimate",
            wall_time=6.0,
        ),
        slot_payload(
            arm_id="llm_agent",
            case_key="taskboard_delete_item_healed",
            task_outcome="false",
            product_passed=True,
            false_heals=1,
            model_requested="deepseek-v4.1-flash",
            model_resolved="deepseek-v4.1-flash-2026-09",
            cost_basis="provider_reported",
        ),
        slot_payload(
            arm_id="healing_replay",
            case_key="taskboard_delete_item_healed",
            status="blocked",
            task_outcome="unscorable",
        ),
    ]


def test_analysis_separates_product_oracle_and_gate_and_reports_denominators() -> None:
    analysis = compute_analysis(manifest_from(minimal_manifest()), base_slots())
    llm = analysis["arms"]["llm_agent"]
    assert llm["product_pass_rate"] == 1.0
    assert llm["oracle"]["known_true"] == 1
    assert llm["oracle"]["known_false"] == 1
    assert llm["false_passes"] == 1
    assert llm["oracle"]["success_lower_bound"] == 0.5
    assert llm["oracle"]["success_upper_bound"] == 0.5
    assert llm["healing"]["false_heals"] == 1
    assert llm["detection"]["detection_ratio"] == 1.0

    healing = analysis["arms"]["healing_replay"]
    assert healing["blocked"] == 1
    assert healing["valid_scheduled"] == 1
    assert healing["oracle"]["unscorable"] == 1
    assert healing["oracle"]["success_upper_bound"] == 1.0
    assert healing["oracle"]["success_lower_bound"] == 0.0


def test_analysis_flags_unverified_model_alias_cache_and_cost_confounds() -> None:
    analysis = compute_analysis(manifest_from(minimal_manifest()), base_slots())
    confounds = analysis["arms"]["llm_agent"]["confounds"]
    assert confounds["unverified_model_alias"] == ["deepseek-v4.1-flash"]
    assert confounds["provider_cache_observed"] is True
    assert confounds["cost_basis_mixed"] is True
    assert confounds["cost_bases"] == ["price_estimate", "provider_reported"]


def test_empty_denominators_are_not_applicable() -> None:
    slots = [slot_payload(arm_id="static_baseline", case_key="taskboard_create_item")]
    analysis = compute_analysis(manifest_from(minimal_manifest()), slots)
    detection = analysis["arms"]["static_baseline"]["detection"]
    assert detection["not_applicable"] is True
    assert detection["detection_ratio"] is None
    healing = analysis["arms"]["static_baseline"]["healing"]
    assert healing["attempt_denominator"]["not_applicable"] is True


def test_comparisons_are_paired_and_seed_pinned() -> None:
    slots = base_slots()
    slots.append(slot_payload(arm_id="static_baseline", case_key="taskboard_delete_item_healed", task_outcome="true"))
    analysis = compute_analysis(manifest_from(minimal_manifest()), slots)
    comparison = analysis["comparisons"][0]
    assert comparison["left"] == "llm_agent"
    assert comparison["right"] == "static_baseline"
    assert comparison["pairs"] == 2
    assert comparison["seed"] == 7
    assert comparison["replicates"] == 500
    assert comparison["sufficient_support"] is True
    assert comparison["p_value"] is not None
    assert analysis["seeds"] == [7]
    assert analysis["analysis_settings"]["bootstrap_replicates"] == 500


def test_rq1_non_inferiority_margin_is_applied() -> None:
    content = minimal_manifest(
        research_question="rq1",
        arms=[
            {"arm_id": "agent_llm_hybrid", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {"arm_id": "agent_llm_vision_first", "mode": "agent", "policy": "llm", "observation": "vision_first"},
        ],
        analysis={
            "primary_endpoints": ["oracle_task_success"],
            "comparisons": [["agent_llm_hybrid", "agent_llm_vision_first"]],
            "bootstrap_seed": 11,
            "bootstrap_replicates": 500,
            "multiple_comparison": "holm",
        },
    )
    content["samples"]["non_inferiority_margin"] = 0.05
    slots = [
        slot_payload(arm_id="agent_llm_hybrid", case_key="taskboard_create_item", task_outcome="true"),
        slot_payload(arm_id="agent_llm_vision_first", case_key="taskboard_create_item", task_outcome="true"),
        slot_payload(arm_id="agent_llm_hybrid", case_key="taskboard_delete_item_healed", task_outcome="false"),
        slot_payload(arm_id="agent_llm_vision_first", case_key="taskboard_delete_item_healed", task_outcome="true"),
    ]
    analysis = compute_analysis(manifest_from(content), slots)
    comparison = analysis["comparisons"][0]
    assert comparison["non_inferiority_margin"] == 0.05
    assert comparison["non_inferior"] is False
    assert comparison["exploratory"] is False


def test_charts_are_built_from_arm_metrics() -> None:
    analysis = compute_analysis(manifest_from(minimal_manifest()), base_slots())
    chart_arms = {entry["arm"] for entry in analysis["charts"]["oracle_success"]}
    assert chart_arms == {arm.arm_id for arm in manifest_from(minimal_manifest()).arms}
    assert analysis["charts"]["false_heals"][0]["arm"] in chart_arms
