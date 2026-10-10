from __future__ import annotations

import subprocess
from pathlib import Path

from tools.ui_harness.runner import run_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ui_admin_roles_settings_end_to_end() -> None:
    dist = REPO_ROOT / "apps" / "web" / "dist" / "index.html"
    if not dist.is_file():
        subprocess.run(
            ["pnpm", "--dir", "apps/web", "build"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            shell=True,
        )
    report = run_scenario(scenario="admin", build_web=True)
    assert report.ok, report.as_dict()
    names = {check.name for check in report.checks if check.ok}
    expected = {
        "settings-owner-create",
        "settings-owner-revoke",
        "no-plaintext-read",
        "provider-readiness",
        "worker-health-visible",
        "viewer-readonly-settings",
        "viewer-api-denied",
    }
    assert expected <= names, sorted(expected - names)
