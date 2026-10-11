from __future__ import annotations

import json
from pathlib import Path

from infra.workloads.common import DEFAULT_THRESHOLDS, percentile, update_latest, write_failure_artifact

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_THRESHOLD_KEYS = {
    "W1": {"max_wall_seconds"},
    "W2": {"max_wall_seconds", "max_peak_reserved"},
    "W3": {"p95_delivery_seconds", "max_wall_seconds"},
    "W4": {"p95_read_seconds", "max_wall_seconds"},
    "W5": {"max_wall_seconds"},
    "W6": {"max_wall_seconds"},
}


def test_percentile_matches_known_vectors() -> None:
    assert percentile([1.0], 0.95) == 1.0
    samples = [float(index) for index in range(1, 101)]
    assert percentile(samples, 0.95) == 95.0
    assert percentile([0.1, 0.2, 0.3, 0.4], 0.5) == 0.2


def test_recompute_p95_from_raw_samples() -> None:
    raw = [0.05 * index for index in range(1, 41)]
    stored_p95 = percentile(raw, 0.95)
    recomputed = percentile(list(reversed(raw)), 0.95)
    assert stored_p95 == recomputed


def test_default_thresholds_match_product_objectives() -> None:
    assert DEFAULT_THRESHOLDS["W3"]["p95_delivery_seconds"] == 1.0
    assert DEFAULT_THRESHOLDS["W4"]["p95_read_seconds"] == 0.5
    for profile, keys in PROFILE_THRESHOLD_KEYS.items():
        assert keys <= set(DEFAULT_THRESHOLDS[profile]), f"thiếu threshold cho {profile}"


def test_update_latest_requires_all_profiles(tmp_path: Path) -> None:
    report_dir = tmp_path / "artifacts" / "workloads"
    report_dir.mkdir(parents=True)
    for profile in ("W1", "W2", "W3"):
        profile_dir = report_dir / profile
        profile_dir.mkdir()
        manifest = {"profile": profile, "ok": profile != "W3", "pinned_before_run": True}
        (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    latest = update_latest(report_dir, tmp_path, [])
    assert latest["ok"] is False
    assert latest["profiles"]["W3"]["ok"] is False


def test_update_latest_all_profiles_pass(tmp_path: Path) -> None:
    report_dir = tmp_path / "artifacts" / "workloads"
    report_dir.mkdir(parents=True)
    for profile in ("W1", "W2", "W3", "W4", "W5", "W6"):
        profile_dir = report_dir / profile
        profile_dir.mkdir()
        (profile_dir / "manifest.json").write_text(
            json.dumps({"profile": profile, "ok": True, "pinned_before_run": True}), encoding="utf-8"
        )
    latest = update_latest(report_dir, tmp_path, [])
    assert latest["ok"] is True
    assert set(latest["profiles"]) == {"W1", "W2", "W3", "W4", "W5", "W6"}


def test_failure_artifact_is_safe_and_informative(tmp_path: Path) -> None:
    from infra.workloads.common import WorkloadContext

    class _Ctx:
        profile = "W9"
        profile_dir = tmp_path / "W9"

    _Ctx.profile_dir.mkdir(parents=True)
    ctx = WorkloadContext(
        repo_root=tmp_path,
        profile="W9",
        profile_dir=_Ctx.profile_dir,
        database="d",
        engines={},
        thresholds={},
    )
    try:
        raise RuntimeError("boom with api_key=sk-do-not-leak")
    except RuntimeError as error:
        write_failure_artifact(ctx, error)
    payload = json.loads((_Ctx.profile_dir / "failure.json").read_text(encoding="utf-8"))
    assert payload["error_type"] == "RuntimeError"
    assert "boom" in payload["error"]
    assert "traceback" in payload


def test_tools_write_expected_latest_artifacts() -> None:
    expectations = {
        "tools/run_ui_e2e.py": 'artifacts" / "ui-e2e"',
        "tools/run_fault_matrix.py": "artifacts/faults",
        "tools/run_os_profile_smoke.py": "artifacts/os-smoke",
        "tools/run_workloads.py": "artifacts/workloads",
    }
    for relative, needle in expectations.items():
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert needle in text or needle.replace('" / "', "/") in text, f"{relative} thiếu {needle}"


def test_acceptance_catalog_artifact_targets_exist_in_tools() -> None:
    from tools.acceptance.catalog import ArtifactCheck, build_catalog

    tool_paths = {check.path for check in build_catalog().checks if isinstance(check, ArtifactCheck)}
    assert "artifacts/faults/latest.json" in tool_paths
    assert "artifacts/ui-e2e/latest.json" in tool_paths
    assert "artifacts/os-smoke/latest.json" in tool_paths
    assert "artifacts/workloads/latest.json" in tool_paths
    assert "artifacts/web-tests/latest.json" in tool_paths
