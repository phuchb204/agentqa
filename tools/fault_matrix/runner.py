from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.fault_matrix.cases import FAULT_CASES, GROUP_ORDER

REPORT_SCHEMA_VERSION = "fault-matrix-report/1"
PYTEST_TIMEOUT_SECONDS = 5400
SANITIZED_ENV_KEYS = frozenset(
    {
        "AGENTQA_JEV_API_KEY",
        "AGENTQA_LLM_API_KEY",
        "AGENTQA_TASKBOARD_CONTROL_TOKEN",
        "AGENTQA_SUPERVISOR_HOST",
        "AGENTQA_SUPERVISOR_PORT",
        "AGENTQA_SUPERVISOR_TOKEN",
        "AGENTQA_WEB_DIST",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitized_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in SANITIZED_ENV_KEYS}


@dataclass
class FaultCaseResult:
    case_id: str
    group: str
    node_id: str
    effect_proof: str
    status: str
    detail: str = ""
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "group": self.group,
            "node_id": self.node_id,
            "effect_proof": self.effect_proof,
            "status": self.status,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 3),
        }


@dataclass
class FaultMatrixReport:
    run_id: str
    models: str
    started_at: str
    finished_at: str
    report_dir: str
    cases: list[FaultCaseResult] = field(default_factory=list)
    pytest_exit: int | None = None
    ok: bool = False
    commit_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        passed = [case for case in self.cases if case.status == "passed"]
        groups: dict[str, dict[str, int]] = {}
        for group in GROUP_ORDER:
            group_cases = [case for case in self.cases if case.group == group]
            groups[group] = {
                "cases": len(group_cases),
                "passed": sum(1 for case in group_cases if case.status == "passed"),
            }
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool": "run_fault_matrix",
            "run_id": self.run_id,
            "models": self.models,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_dir": self.report_dir,
            "commit_sha": self.commit_sha,
            "pytest_exit": self.pytest_exit,
            "cases_total": len(self.cases),
            "cases_passed": len(passed),
            "groups": groups,
            "cases": [case.as_dict() for case in self.cases],
            "ok": self.ok,
        }


def _parse_junit(path: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    tree = ET.parse(path)
    for suite in tree.iter("testsuite"):
        for case in suite.iter("testcase"):
            classname = case.get("classname") or ""
            name = case.get("name") or ""
            node = f"{classname}::{name}"
            if case.find("failure") is not None:
                statuses[node] = "failed"
            elif case.find("error") is not None:
                statuses[node] = "error"
            elif case.find("skipped") is not None:
                statuses[node] = "skipped"
            else:
                statuses[node] = "passed"
    return statuses


def _node_key(node_id: str) -> str:
    path, _, test_name = node_id.partition("::")
    module = path.removesuffix(".py").replace("/", ".")
    return f"{module}::{test_name}"


def _git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def run_matrix(*, repo_root: Path, report_dir: Path, models: str = "fake") -> FaultMatrixReport:
    if models != "fake":
        raise ValueError(f"fault matrix chỉ chạy với --models fake, nhận: {models}")
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    run_dir = report_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = _now_iso()
    node_ids = [case.node_id for case in FAULT_CASES]
    junit_path = run_dir / "faults-junit.xml"
    log_path = run_dir / "faults.log"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit_path}",
        *node_ids,
    ]
    pytest_exit: int | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=_sanitized_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
        pytest_exit = completed.returncode
        log_path.write_text(
            "\n".join(
                [
                    " ".join(command),
                    f"exit={completed.returncode}",
                    "--- stdout ---",
                    completed.stdout or "",
                    "--- stderr ---",
                    completed.stderr or "",
                ]
            ),
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        log_path.write_text(f"timeout {PYTEST_TIMEOUT_SECONDS}s", encoding="utf-8")
    statuses: dict[str, str] = {}
    if junit_path.is_file():
        try:
            statuses = _parse_junit(junit_path)
        except ET.ParseError:
            statuses = {}
    results: list[FaultCaseResult] = []
    durations: dict[str, float] = {}
    for case in FAULT_CASES:
        key = _node_key(case.node_id)
        status = statuses.get(key)
        if status == "passed":
            results.append(FaultCaseResult(case.id, case.group, case.node_id, case.effect_proof, "passed"))
        elif status is None:
            results.append(
                FaultCaseResult(
                    case.id,
                    case.group,
                    case.node_id,
                    case.effect_proof,
                    "not_run",
                    "không có kết quả pytest cho node id (collect/selection lỗi?)",
                )
            )
        else:
            results.append(
                FaultCaseResult(
                    case.id,
                    case.group,
                    case.node_id,
                    case.effect_proof,
                    "failed",
                    f"pytest status {status}",
                )
            )
    for result in results:
        result.duration_s = durations.get(result.case_id, 0.0)
    report = FaultMatrixReport(
        run_id=run_id,
        models=models,
        started_at=started_at,
        finished_at=_now_iso(),
        report_dir=str(run_dir),
        cases=results,
        pytest_exit=pytest_exit,
        ok=all(case.status == "passed" for case in results),
        commit_sha=_git_commit(repo_root),
    )
    payload = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    (run_dir / "report.json").write_text(payload + "\n", encoding="utf-8")
    (report_dir / "latest.json").write_text(payload + "\n", encoding="utf-8")
    return report
