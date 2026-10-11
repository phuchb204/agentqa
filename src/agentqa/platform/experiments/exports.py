from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agentqa.platform.experiments.analysis import analysis_digest, compute_analysis
from agentqa.platform.experiments.manifests import ExperimentManifest

BUNDLE_SCHEMA = "research-bundle/1"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_bundle(*, results: dict[str, Any], analysis: dict[str, Any]) -> dict[str, str]:
    manifest = results["manifest"]
    slots = results["slots"]
    files: dict[str, str] = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "slots.jsonl": "".join(
            json.dumps(_safe_slot(slot), ensure_ascii=False, sort_keys=True) + "\n" for slot in slots
        ),
        "metrics.json": json.dumps(analysis, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "metric-definitions.json": json.dumps(
            analysis.get("metric_definitions", {}), ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n",
        "analysis-settings.json": json.dumps(
            {
                "settings": analysis.get("analysis_settings", {}),
                "seeds": analysis.get("seeds", []),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    }
    integrity = {
        "schema_version": BUNDLE_SCHEMA,
        "files": {name: _sha256(text) for name, text in sorted(files.items())},
        "manifest_digest": results.get("content_digest"),
        "analysis_digest": analysis_digest(analysis),
        "oracle_raw_included": False,
    }
    files["integrity.json"] = json.dumps(integrity, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return files


def _safe_slot(slot: dict[str, Any]) -> dict[str, Any]:
    payload = slot.get("payload") or {}
    return {
        "slot_key": slot["slot_key"],
        "arm_id": slot["arm_id"],
        "case_key": slot["case_key"],
        "variant_token": slot.get("variant_token"),
        "data_row": slot.get("data_row"),
        "repetition": slot.get("repetition"),
        "attempt_no": slot.get("attempt_no"),
        "status": slot["status"],
        "blocked_reason": slot.get("blocked_reason"),
        "product": payload.get("product"),
        "oracle": payload.get("oracle"),
        "gate": payload.get("gate"),
        "usage": payload.get("usage"),
        "model_requested": payload.get("model_requested"),
        "model_resolved": payload.get("model_resolved"),
        "provider_cache_observed": payload.get("provider_cache_observed"),
        "cost_basis": payload.get("cost_basis"),
    }


def write_bundle(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def load_bundle(root: Path) -> dict[str, Any]:
    files = {path.name: path.read_text(encoding="utf-8") for path in sorted(root.iterdir()) if path.is_file()}
    return files


def _analysis_slot(line: dict[str, Any]) -> dict[str, Any]:
    payload_keys = (
        "product",
        "oracle",
        "gate",
        "usage",
        "model_requested",
        "model_resolved",
        "provider_cache_observed",
        "cost_basis",
    )
    return {
        "slot_key": line.get("slot_key"),
        "arm_id": line.get("arm_id"),
        "case_key": line.get("case_key"),
        "variant_token": line.get("variant_token"),
        "data_row": line.get("data_row"),
        "repetition": line.get("repetition"),
        "attempt_no": line.get("attempt_no"),
        "status": line.get("status"),
        "blocked_reason": line.get("blocked_reason"),
        "payload": {key: line.get(key) for key in payload_keys},
    }


def recompute(root: Path) -> dict[str, Any]:
    files = load_bundle(root)
    manifest = ExperimentManifest.model_validate(json.loads(files["manifest.json"]))
    slots = [_analysis_slot(json.loads(line)) for line in files["slots.jsonl"].splitlines() if line.strip()]
    fresh = compute_analysis(manifest, slots)
    stored = json.loads(files["metrics.json"])
    diffs: list[str] = []
    for arm_id, metrics in stored.get("arms", {}).items():
        fresh_metrics = fresh["arms"].get(arm_id)
        if fresh_metrics is None:
            diffs.append(f"arm_missing:{arm_id}")
            continue
        for field in ("oracle", "healing", "false_passes", "usage", "confounds", "completed", "blocked", "errors"):
            if metrics.get(field) != fresh_metrics.get(field):
                diffs.append(f"{arm_id}.{field}")
    for index, comparison in enumerate(stored.get("comparisons", [])):
        fresh_comparison = fresh["comparisons"][index] if index < len(fresh["comparisons"]) else None
        if fresh_comparison is None:
            diffs.append(f"comparison_missing:{index}")
            continue
        for field in ("left", "right", "pairs", "estimate", "lower", "upper", "sufficient_support"):
            if comparison.get(field) != fresh_comparison.get(field):
                diffs.append(f"comparison[{index}].{field}")
    integrity = json.loads(files["integrity.json"])
    for name, digest in integrity.get("files", {}).items():
        if name in files and _sha256(files[name]) != digest:
            diffs.append(f"integrity:{name}")
    return {
        "matches": not diffs,
        "diffs": diffs,
        "charts": fresh["charts"],
        "analysis": fresh,
    }
