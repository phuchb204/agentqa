from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.release.validation import (
    EXPECTED_AC,
    EXPECTED_NFR,
    UI_SCENARIOS,
    WORKLOAD_PROFILES,
    validate_release,
)

FUTURE = (datetime.now(UTC) + timedelta(days=7)).isoformat()


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(root: Path, rel: str, payload: dict) -> None:
    _write(root, rel, json.dumps(payload, ensure_ascii=False))


def _build_ready_repo(root: Path, *, calibration_bound: float = 0.005) -> None:
    scenarios = [{"id": item} for item in (*EXPECTED_AC, *EXPECTED_NFR)]
    _write_json(
        root,
        "artifacts/acceptance/latest.json",
        {"ok": True, "filtered": False, "run_id": "test-run", "scenarios": scenarios},
    )
    _write_json(root, "artifacts/faults/latest.json", {"ok": True, "cases_total": 24, "cases_passed": 24})
    _write_json(
        root,
        "artifacts/ui-e2e/latest.json",
        {"ok": True, "scenarios": [{"name": name, "ok": True} for name in UI_SCENARIOS]},
    )
    _write_json(
        root,
        "artifacts/os-smoke/latest.json",
        {"ok": True, "profiles": {"windows": {"ok": True}, "linux": {"ok": True}}},
    )
    _write_json(
        root,
        "artifacts/workloads/latest.json",
        {"ok": True, "profiles": {name: {"ok": True, "pinned_before_run": True} for name in WORKLOAD_PROFILES}},
    )
    _write_json(root, "artifacts/web-tests/latest.json", {"ok": True, "tests_passed": 53})
    _write_json(
        root,
        "artifacts/model-capabilities/opencode_go-receipt.json",
        {
            "capabilities": {"text": "verified", "image": "verified"},
            "expires_at": FUTURE,
            "version_identity": "unverified",
        },
    )
    _write_json(
        root,
        "artifacts/model-capabilities/opencode_zen-receipt.json",
        {
            "capabilities": {"text": "verified", "image": "unsupported"},
            "expires_at": FUTURE,
            "version_identity": "unverified",
        },
    )
    _write_json(
        root,
        "artifacts/calibration/healing-default-test.json",
        {"bound_upper": calibration_bound, "evidence": "measured", "profile_id": "healing-default"},
    )
    _write_json(root, "artifacts/research/rq1-test/metrics.json", {"ok": True})
    _write(root, "docs/runbooks/quickstart.md", "# quickstart")
    _write(root, "docs/runbooks/demo.md", "# demo")
    _write(root, "docs/runbooks/research-reproduction.md", "# research")
    _write(root, "docs/runbooks/release-validation.md", "# release")
    _write(root, "CHANGELOG.md", "# changelog")
    _write(root, "uv.lock", 'version = 1\n\n[[package]]\nname = "agentqa"\nversion = "0.1.0"\n')
    _write(root, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n\npackages:\n  /left-pad@1.3.0: {}\n")
    _write(root, "apps/web/dist/index.html", "<html></html>")


def test_missing_acceptance_fails_structurally(tmp_path: Path) -> None:
    report = validate_release(tmp_path, require_p32=False)
    assert report.structural_ok is False
    assert report.full_release is False
    acceptance = next(check for check in report.checks if check.id == "acceptance")
    assert acceptance.ok is False


def test_provisional_calibration_blocks_full_release(tmp_path: Path) -> None:
    _build_ready_repo(tmp_path, calibration_bound=0.776)
    report = validate_release(tmp_path)
    assert report.structural_ok is True
    assert report.full_release is False
    assert "calibration_healing_profile" in report.provisional
    assert any("provisional" in reason for reason in report.reasons)


def test_full_release_ready_when_everything_passes(tmp_path: Path) -> None:
    _build_ready_repo(tmp_path)
    report = validate_release(tmp_path)
    assert report.structural_ok is True
    assert report.provisional == []
    assert report.full_release is True
    assert report.coverage["fr_missing"] == []
    assert report.gates["G8"]["ok"] is True


def test_expired_live_receipt_blocks_full_release(tmp_path: Path) -> None:
    _build_ready_repo(tmp_path)
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _write_json(
        tmp_path,
        "artifacts/model-capabilities/opencode_go-receipt.json",
        {"capabilities": {"text": "verified", "image": "verified"}, "expires_at": expired},
    )
    report = validate_release(tmp_path)
    assert report.structural_ok is True
    assert report.full_release is False
    assert any("hết hạn" in reason for reason in report.reasons)
    assert report.gates["G3"]["ok"] is False


def test_missing_runbook_blocks_p32(tmp_path: Path) -> None:
    _build_ready_repo(tmp_path)
    (tmp_path / "docs" / "runbooks" / "demo.md").unlink()
    report = validate_release(tmp_path)
    assert report.full_release is False
    assert any("P32" in reason for reason in report.reasons)
