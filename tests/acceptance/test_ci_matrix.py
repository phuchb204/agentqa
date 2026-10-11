from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

CORE_GATES = (
    "ruff check .",
    "ruff format --check .",
    "lint-imports",
    "export_schemas.py --check",
    "check_plan_coverage.py",
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps_text(job: dict) -> str:
    return "\n".join(str(step) for step in job.get("steps", []))


def _setup_step(job: dict, action: str) -> dict | None:
    for step in job.get("steps", []):
        if str(step.get("uses", "")).startswith(action):
            return step
    return None


def test_workflow_has_linux_and_windows_jobs() -> None:
    jobs = _workflow()["jobs"]
    runners = {job.get("runs-on") for job in jobs.values()}
    assert "ubuntu-latest" in runners
    assert "windows-latest" in runners


def test_runtime_pins_python_and_node() -> None:
    assert (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"
    jobs = _workflow()["jobs"]
    for name in ("python", "python-windows"):
        step = _setup_step(jobs[name], "astral-sh/setup-uv")
        assert step is not None, f"{name}: thiếu setup-uv"
        assert str(step.get("with", {}).get("version", "")).strip(), f"{name}: setup-uv thiếu version pin"
        assert "uv python install" in _steps_text(jobs[name])
    node = _setup_step(jobs["web"], "actions/setup-node")
    assert node is not None
    assert str(node.get("with", {}).get("node-version")) == "24"


def test_linux_job_runs_core_gates_and_database() -> None:
    job = _workflow()["jobs"]["python"]
    text = _steps_text(job)
    for gate in CORE_GATES:
        assert gate in text, f"gate thiếu trong job python: {gate}"
    assert "pytest -q" in text
    assert "run_os_profile_smoke.py --profile linux" in text
    assert job.get("services", {}).get("postgres", {}).get("image") == "postgres:18"


def test_windows_job_runs_gates_and_os_smoke() -> None:
    job = _workflow()["jobs"]["python-windows"]
    text = _steps_text(job)
    for gate in CORE_GATES:
        assert gate in text, f"gate thiếu trong job python-windows: {gate}"
    assert "pytest -q tests/contracts tests/foundation tests/acceptance" in text
    assert "run_os_profile_smoke.py --profile windows" in text
    assert "playwright install chromium" in text


def test_web_job_runs_frontend_gates() -> None:
    text = _steps_text(_workflow()["jobs"]["web"])
    for gate in (
        "pnpm --dir apps/web lint",
        "pnpm --dir apps/web typecheck",
        "pnpm --dir apps/web test",
        "pnpm --dir apps/web build",
    ):
        assert gate in text
