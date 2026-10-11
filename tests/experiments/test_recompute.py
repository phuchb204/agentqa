from __future__ import annotations

import json

from agentqa.platform.cli import main as cli_main
from agentqa.platform.experiments import build_bundle, compute_analysis, recompute, write_bundle
from tests.experiments.conftest import manifest_from, minimal_manifest, slot_payload


def make_bundle(root) -> None:
    slots = [
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
            wall_time=5.0,
        ),
        slot_payload(
            arm_id="llm_agent",
            case_key="taskboard_delete_item_healed",
            task_outcome="false",
            product_passed=True,
            false_heals=1,
        ),
    ]
    manifest = minimal_manifest()
    results = {
        "revision_id": "r1",
        "content_digest": manifest_from(manifest).digest(),
        "manifest": manifest,
        "slots": slots,
    }
    analysis = compute_analysis(manifest_from(manifest), slots)
    write_bundle(root, build_bundle(results=results, analysis=analysis))


def test_offline_recompute_matches_backend_metrics_and_charts(tmp_path) -> None:
    root = tmp_path / "export"
    make_bundle(root)
    report = recompute(root)
    assert report["matches"] is True
    assert report["diffs"] == []
    assert report["charts"]["oracle_success"]
    stored = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    assert report["analysis"]["arms"]["llm_agent"]["false_passes"] == stored["arms"]["llm_agent"]["false_passes"]


def test_recompute_detects_tampered_metrics(tmp_path) -> None:
    root = tmp_path / "export"
    make_bundle(root)
    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    metrics["arms"]["llm_agent"]["false_passes"] = 99
    (root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    report = recompute(root)
    assert report["matches"] is False
    assert any("false_passes" in diff for diff in report["diffs"])
    assert any(diff.startswith("integrity:") for diff in report["diffs"])


def test_cli_recompute_is_offline_and_exit_zero(tmp_path) -> None:
    root = tmp_path / "export"
    make_bundle(root)
    assert cli_main(["--json", "experiment", "recompute", "--bundle", str(root)]) == 0


def test_recompute_uses_no_model_calls(tmp_path) -> None:
    root = tmp_path / "export"
    make_bundle(root)
    report = recompute(root)
    payload = json.dumps(report, ensure_ascii=False)
    for forbidden in ("api_key", "Authorization", "model_call"):
        assert forbidden not in payload
