from __future__ import annotations

import hashlib
import json

from agentqa.platform.experiments import build_bundle, compute_analysis, write_bundle
from tests.experiments.conftest import manifest_from, minimal_manifest, slot_payload


def results_fixture() -> dict:
    slots = [
        slot_payload(
            arm_id="static_baseline",
            case_key="taskboard_create_item",
            task_outcome="true",
            detected=1,
            correct_heals=1,
            wall_time=1.5,
        ),
        slot_payload(
            arm_id="llm_agent",
            case_key="taskboard_create_item",
            task_outcome="false",
            product_passed=True,
            false_heals=1,
            model_requested="deepseek-v4.1-flash",
        ),
    ]
    manifest = minimal_manifest()
    return {
        "revision_id": "00000000-0000-0000-0000-000000000001",
        "content_digest": manifest_from(manifest).digest(),
        "manifest": manifest,
        "slots": slots,
    }


def test_bundle_contains_manifest_metrics_settings_and_integrity(tmp_path) -> None:
    results = results_fixture()
    analysis = compute_analysis(manifest_from(results["manifest"]), results["slots"])
    files = build_bundle(results=results, analysis=analysis)
    assert set(files) == {
        "manifest.json",
        "slots.jsonl",
        "metrics.json",
        "metric-definitions.json",
        "analysis-settings.json",
        "integrity.json",
    }
    integrity = json.loads(files["integrity.json"])
    assert integrity["schema_version"] == "research-bundle/1"
    assert integrity["oracle_raw_included"] is False
    assert integrity["manifest_digest"] == results["content_digest"]
    for name, digest in integrity["files"].items():
        assert hashlib.sha256(files[name].encode("utf-8")).hexdigest() == digest
    settings = json.loads(files["analysis-settings.json"])
    assert settings["settings"]["bootstrap_replicates"] == 500
    assert settings["seeds"] == [7]
    root = write_bundle(tmp_path / "export", files)
    assert (root / "manifest.json").is_file()
    assert (root / "slots.jsonl").is_file()


def test_slots_jsonl_is_deidentified_and_has_no_raw_oracle() -> None:
    results = results_fixture()
    analysis = compute_analysis(manifest_from(results["manifest"]), results["slots"])
    files = build_bundle(results=results, analysis=analysis)
    lines = [json.loads(line) for line in files["slots.jsonl"].splitlines() if line.strip()]
    assert len(lines) == 2
    text = files["slots.jsonl"]
    for forbidden in ("expected_effects", "opportunities", "applied_patch", "oracle_assertions_ref"):
        assert forbidden not in text
    first = lines[0]
    assert set(first) >= {"slot_key", "arm_id", "status", "product", "oracle", "usage"}


def test_metric_definitions_explain_denominators() -> None:
    results = results_fixture()
    analysis = compute_analysis(manifest_from(results["manifest"]), results["slots"])
    files = build_bundle(results=results, analysis=analysis)
    definitions = json.loads(files["metric-definitions.json"])
    assert "valid_scheduled" in definitions["oracle_task_success"]
    assert "detected" in definitions["detection_ratio"]
    assert "oracle false" in definitions["false_pass"]
