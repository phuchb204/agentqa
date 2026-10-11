from __future__ import annotations

from collections import defaultdict
from typing import Any

from agentqa.contracts.canonical import digest_content
from agentqa.platform.evaluation.scoring import success_bounds
from agentqa.platform.experiments.manifests import ExperimentManifest
from agentqa.platform.statistics.missingness import denominator
from agentqa.platform.statistics.multiple import holm_adjust
from agentqa.platform.statistics.paired import paired_bootstrap


def _arm_metrics(slots: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [slot for slot in slots if slot["status"] in ("completed", "blocked", "error")]
    completed = [slot for slot in slots if slot["status"] == "completed"]
    product_passed = 0
    known_true = known_false = unscorable = 0
    detected = missed = attempts = correct = false_heals = refusals = 0
    false_passes = 0
    usage_calls = usage_input = usage_output = 0
    wall_time = 0.0
    unverified_models: set[str] = set()
    cache_observed = False
    cost_bases: set[str] = set()
    for slot in valid:
        payload = slot.get("payload") or {}
        oracle = payload.get("oracle") or {}
        outcome = oracle.get("task_outcome")
        if outcome == "true":
            known_true += 1
        elif outcome == "false":
            known_false += 1
        else:
            unscorable += 1
    for slot in completed:
        payload = slot.get("payload") or {}
        product = payload.get("product") or {}
        oracle = payload.get("oracle") or {}
        if product.get("verdict") == "passed" and product.get("gate") in ("passed", None):
            product_passed += 1
        counters = oracle.get("counters") or {}
        detected += int(counters.get("detected", 0))
        missed += int(counters.get("missed", 0))
        attempts += int(counters.get("attempts_total", 0))
        correct += int(counters.get("correct_heals", 0))
        false_heals += int(counters.get("false_heals", 0))
        refusals += int(counters.get("refusals", 0))
        if oracle.get("false_pass"):
            false_passes += 1
        usage = payload.get("usage") or {}
        usage_calls += int(usage.get("calls", 0))
        usage_input += int(usage.get("input_tokens", 0) or 0)
        usage_output += int(usage.get("output_tokens", 0) or 0)
        wall_time += float(usage.get("wall_time_seconds", 0.0) or 0.0)
        resolved = payload.get("model_resolved")
        requested = payload.get("model_requested")
        if requested and (not resolved or resolved == requested):
            unverified_models.add(str(requested))
        if payload.get("provider_cache_observed"):
            cache_observed = True
        basis = payload.get("cost_basis")
        if basis:
            cost_bases.add(str(basis))
    lower, upper, coverage = success_bounds(known_true, unscorable, len(valid))
    detection_denominator = detected + missed
    return {
        "slots_total": len(slots),
        "valid_scheduled": len(valid),
        "completed": len(completed),
        "blocked": sum(1 for slot in slots if slot["status"] == "blocked"),
        "errors": sum(1 for slot in slots if slot["status"] == "error"),
        "product_pass_rate": (product_passed / len(completed)) if completed else None,
        "product_denominator": denominator(completed).__dict__,
        "oracle": {
            "known_true": known_true,
            "known_false": known_false,
            "unscorable": unscorable,
            "success_lower_bound": lower,
            "success_upper_bound": upper,
            "coverage": coverage,
            "unscorable_ratio": (unscorable / len(valid)) if valid else None,
        },
        "detection": {
            "detected": detected,
            "missed": missed,
            "precision_denominator": detection_denominator,
            "detection_ratio": (detected / detection_denominator) if detection_denominator else None,
            "not_applicable": detection_denominator == 0,
        },
        "healing": {
            "attempts": attempts,
            "correct_heals": correct,
            "false_heals": false_heals,
            "refusals": refusals,
            "attempt_denominator": denominator([1] * attempts).__dict__,
        },
        "false_passes": false_passes,
        "usage": {
            "calls": usage_calls,
            "input_tokens": usage_input,
            "output_tokens": usage_output,
            "wall_time_seconds": round(wall_time, 3),
        },
        "confounds": {
            "unverified_model_alias": sorted(unverified_models),
            "provider_cache_observed": cache_observed,
            "cost_basis_mixed": len(cost_bases) > 1,
            "cost_bases": sorted(cost_bases),
        },
    }


def _pairs_for_arm(slots: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    pairs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for slot in slots:
        if slot["status"] != "completed":
            continue
        payload = slot.get("payload") or {}
        oracle = payload.get("oracle") or {}
        success = 1.0 if oracle.get("task_outcome") == "true" else 0.0
        if oracle.get("task_outcome") not in ("true", "false"):
            continue
        key = (slot["case_key"], slot.get("variant_token") or "-", str(slot.get("data_row") or "-"))
        pairs[key] = {
            "success": success,
            "wall": float((payload.get("usage") or {}).get("wall_time_seconds", 0.0) or 0.0),
        }
    return pairs


def compute_analysis(manifest: ExperimentManifest, slots: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        by_arm[slot["arm_id"]].append(slot)
    arms = {arm.arm_id: _arm_metrics(by_arm.get(arm.arm_id, [])) for arm in manifest.arms}

    comparisons: list[dict[str, Any]] = []
    p_values: list[float] = []
    labels: list[str] = []
    for left_id, right_id in manifest.analysis.comparisons:
        left_pairs = _pairs_for_arm(by_arm.get(left_id, []))
        right_pairs = _pairs_for_arm(by_arm.get(right_id, []))
        shared = sorted(set(left_pairs) & set(right_pairs))
        strata: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for key in shared:
            strata[key[0]].append((left_pairs[key]["success"], right_pairs[key]["success"]))
        result = paired_bootstrap(
            strata,
            confidence=manifest.samples.confidence,
            replicates=manifest.analysis.bootstrap_replicates,
            seed=manifest.analysis.bootstrap_seed,
        )
        p_value = None
        if result.sufficient_support and result.p_value is not None:
            p_value = result.p_value
            labels.append(f"{left_id}_vs_{right_id}")
            p_values.append(p_value)
        comparison = {
            "left": left_id,
            "right": right_id,
            "pairs": len(shared),
            "estimate": result.estimate,
            "lower": result.lower,
            "upper": result.upper,
            "confidence": result.confidence,
            "seed": result.seed,
            "replicates": result.replicates,
            "sufficient_support": result.sufficient_support,
            "reason": result.reason,
            "p_value": p_value,
            "exploratory": True,
        }
        if (
            manifest.research_question == "rq1"
            and manifest.samples.non_inferiority_margin is not None
            and left_id == "agent_llm_hybrid"
            and right_id == "agent_llm_vision_first"
        ):
            margin = manifest.samples.non_inferiority_margin
            comparison["non_inferiority_margin"] = margin
            comparison["non_inferior"] = None if result.lower is None else result.lower >= -margin
            comparison["exploratory"] = False
        comparisons.append(comparison)
    if p_values:
        adjusted = holm_adjust(labels, p_values, alpha=1.0 - manifest.samples.confidence)
        for comparison, label in zip(
            (item for item in comparisons if item["p_value"] is not None), labels, strict=True
        ):
            index = labels.index(label)
            comparison["holm_adjusted_p"] = adjusted.adjusted[index]
            comparison["holm_rejected"] = adjusted.rejected[index]

    return {
        "manifest_digest": manifest.digest(),
        "analysis_settings": manifest.analysis.model_dump(mode="json"),
        "seeds": list(manifest.seeds),
        "arms": arms,
        "comparisons": comparisons,
        "metric_definitions": {
            "oracle_task_success": (
                "known_true / valid_scheduled (lower) và (known_true+unscorable)/valid_scheduled (upper)"
            ),
            "false_pass": "product passed và oracle false trên cùng slot",
            "detection_ratio": "detected / (detected + missed) trên oracle opportunities",
        },
        "charts": _charts(arms),
    }


def _charts(arms: dict[str, Any]) -> dict[str, Any]:
    return {
        "oracle_success": [
            {
                "arm": arm_id,
                "lower": metrics["oracle"]["success_lower_bound"],
                "upper": metrics["oracle"]["success_upper_bound"],
            }
            for arm_id, metrics in sorted(arms.items())
        ],
        "false_heals": [
            {"arm": arm_id, "false_heals": metrics["healing"]["false_heals"]}
            for arm_id, metrics in sorted(arms.items())
        ],
        "wall_time": [
            {"arm": arm_id, "wall_time_seconds": metrics["usage"]["wall_time_seconds"]}
            for arm_id, metrics in sorted(arms.items())
        ],
    }


def analysis_digest(analysis: dict[str, Any]) -> str:
    return digest_content(analysis)
