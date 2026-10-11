from __future__ import annotations

import json
from pathlib import Path

from tools.acceptance.catalog import build_catalog
from tools.acceptance.runner import run_catalog, summarize

from tests.acceptance.test_runner import FakeExecutor


def _write_full_report(tmp_path: Path) -> None:
    catalog = build_catalog()
    run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=FakeExecutor())


def _write_workloads(tmp_path: Path, *, pinned: bool = True, ok: bool = True) -> None:
    for profile in ("W1", "W2", "W3", "W4", "W5", "W6"):
        profile_dir = tmp_path / "artifacts" / "workloads" / profile
        profile_dir.mkdir(parents=True)
        manifest = {
            "profile": profile,
            "ok": ok,
            "pinned_before_run": pinned,
            "thresholds": {"p95_delivery_seconds": 1.0},
            "metrics_path": f"artifacts/workloads/{profile}/metrics.json",
            "generated_at": "2026-10-11T00:00:00Z",
        }
        (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        metrics = {"generated_at": "2026-10-11T00:05:00Z", "p95_delivery_seconds": 0.4}
        (profile_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_summary_requires_latest_report(tmp_path: Path) -> None:
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("latest.json" in gap for gap in result.gaps)


def test_summary_detects_missing_workloads(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("W1" in gap for gap in result.gaps)
    assert any("W6" in gap for gap in result.gaps)


def test_summary_full_pass(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    _write_workloads(tmp_path)
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.gaps == []
    assert result.ok is True
    assert len(result.scenarios) == 36
    assert len(result.workloads) == 6


def test_summary_rejects_unpinned_workload(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    _write_workloads(tmp_path, pinned=False)
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("pin" in gap for gap in result.gaps)


def test_summary_rejects_failed_workload(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    _write_workloads(tmp_path, ok=False)
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("ok != true" in gap for gap in result.gaps)


def test_summary_rejects_manifest_after_metrics(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    _write_workloads(tmp_path)
    manifest_path = tmp_path / "artifacts" / "workloads" / "W2" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generated_at"] = "2026-10-11T00:10:00Z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("pin trước khi đo" in gap for gap in result.gaps)


def test_summary_rejects_filtered_report(tmp_path: Path) -> None:
    _write_full_report(tmp_path)
    latest_path = tmp_path / "latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    payload["filtered"] = True
    latest_path.write_text(json.dumps(payload), encoding="utf-8")
    result = summarize(repo_root=tmp_path, report_dir=tmp_path)
    assert result.ok is False
    assert any("filter" in gap for gap in result.gaps)
