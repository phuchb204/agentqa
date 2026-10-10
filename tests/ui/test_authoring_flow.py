from __future__ import annotations

import subprocess
from pathlib import Path

from tools.ui_harness.runner import run_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ui_authoring_flow_end_to_end() -> None:
    dist = REPO_ROOT / "apps" / "web" / "dist" / "index.html"
    if not dist.is_file():
        subprocess.run(
            ["pnpm", "--dir", "apps/web", "build"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            shell=True,
        )
    report = run_scenario(scenario="authoring", build_web=False)
    assert report.ok, report.as_dict()
    names = {check.name for check in report.checks if check.ok}
    expected = {
        "role-aware-login",
        "keyboard-focus",
        "no-inherited-provider-creds",
        "source-upload-quarantine",
        "authoring-proposal",
        "proposal-apply-diff",
        "promote-ready",
        "draft-run-provisional",
        "no-auto-ready",
        "stale-edit-conflict",
        "strict-replay-passed",
        "canary-absent-events",
    }
    assert expected <= names, sorted(expected - names)
    assert report.run_verdict == "passed"
    assert report.draft_run_verdict == "inconclusive"
