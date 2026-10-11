from __future__ import annotations

import json
from pathlib import Path

from tools.acceptance.canary_scan import run_canary_scan

CANARY = "canary-synthetic-4b91d0"


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_passes_on_clean_artifacts(tmp_path: Path) -> None:
    _write(tmp_path, "artifacts/ui-e2e/run/report.json", json.dumps({"ok": True}))
    _write(tmp_path, "artifacts/acceptance/run/report.json", json.dumps({"ok": True}))
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is True
    assert result["scanned_files"] == 2
    assert result["matches"] == []


def test_scan_detects_known_literal(tmp_path: Path) -> None:
    _write(tmp_path, "artifacts/ui-e2e/run/harness.log", f"provider key={CANARY} used")
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is False
    assert any(match["kind"] == "literal" and match["value"] == CANARY for match in result["matches"])


def test_scan_detects_unknown_pattern(tmp_path: Path) -> None:
    _write(tmp_path, "artifacts/workloads/W1/metrics.json", '{"note": "canary-abcdef1234 leaked"}')
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is False
    assert any(match["kind"] == "pattern" for match in result["matches"])


def test_scan_ignores_test_identifier_names(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "artifacts/acceptance/run/pytest-junit.xml",
        (
            'name="canary_is_blocked_before_storage" '
            'name="test_canary_is_blocked" '
            'name="canary_out_of_sinks" '
            'name="canary_pixel_check"'
        ),
    )
    _write(tmp_path, "artifacts/ui-e2e/latest.json", '{"checks": [{"name": "canary-absent-events"}]}')
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is True
    assert result["matches"] == []


def test_scan_skips_own_report_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "artifacts/acceptance/canary-scan.json",
        json.dumps({"matches": [{"value": CANARY}]}),
    )
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is True
    assert result["scanned_files"] == 0


def test_scan_ignores_missing_roots(tmp_path: Path) -> None:
    result = run_canary_scan(repo_root=tmp_path)
    assert result["ok"] is True
    assert result["scanned_files"] == 0
