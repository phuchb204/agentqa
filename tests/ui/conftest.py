from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tools.ui_harness.runner import run_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def live_report():
    dist = REPO_ROOT / "apps" / "web" / "dist" / "index.html"
    if not dist.is_file():
        subprocess.run(
            ["pnpm", "--dir", "apps/web", "build"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            shell=True,
        )
    report = run_scenario(scenario="live", build_web=False)
    return report
