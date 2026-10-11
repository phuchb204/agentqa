from __future__ import annotations

import glob
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tools.acceptance.catalog import (
    EXPECTED_AC,
    EXPECTED_NFR,
    ArtifactCheck,
    Catalog,
    CommandCheck,
    FunctionCheck,
    PytestCheck,
    Scenario,
    check_kind,
    validate_catalog,
)

REPORT_SCHEMA_VERSION = "acceptance-report/1"
PYTEST_TIMEOUT_SECONDS = 7200
COMMAND_TIMEOUT_SECONDS = 900
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
WORKLOAD_PROFILES = ("W1", "W2", "W3", "W4", "W5", "W6")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sanitized_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in SANITIZED_ENV_KEYS}


@dataclass
class CheckOutcome:
    check_id: str
    kind: str
    status: str
    detail: str
    duration_s: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 3),
            "evidence": self.evidence,
        }


class CatalogExecutor(Protocol):
    def run(self, catalog: Catalog) -> dict[str, CheckOutcome]: ...


def _file_from_classname(classname: str | None) -> str | None:
    if not classname:
        return None
    parts = classname.split(".")
    if not parts:
        return None
    return "/".join(parts) + ".py"


def _parse_junit(path: Path) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    tree = ET.parse(path)
    for suite in tree.iter("testsuite"):
        for case in suite.iter("testcase"):
            file_attr = case.get("file") or _file_from_classname(case.get("classname"))
            key = file_attr.replace("\\", "/") if file_attr else "__unknown__"
            entry = stats.setdefault(key, {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0})
            entry["tests"] += 1
            if case.find("failure") is not None:
                entry["failed"] += 1
            elif case.find("error") is not None:
                entry["errors"] += 1
            elif case.find("skipped") is not None:
                entry["skipped"] += 1
            else:
                entry["passed"] += 1
    return stats


def _aggregate_stats(totals: dict[str, int], target: str, stats: dict[str, dict[str, int]]) -> tuple[bool, str]:
    if not target.endswith(".py"):
        prefix = target.rstrip("/") + "/"
        files = [name for name in stats if name.startswith(prefix)]
    else:
        files = [target] if target in stats else []
    if not files:
        return False, f"không có kết quả pytest cho {target}"
    for name in sorted(files):
        entry = stats[name]
        for key in ("tests", "passed", "failed", "errors", "skipped"):
            totals[key] = totals.get(key, 0) + entry[key]
    return True, ""


class CatalogCommandExecutor:
    def __init__(self, *, repo_root: Path, report_dir: Path) -> None:
        self.repo_root = repo_root
        self.report_dir = report_dir
        self.env = sanitized_env()

    def run(self, catalog: Catalog) -> dict[str, CheckOutcome]:
        outcomes: dict[str, CheckOutcome] = {}
        pytest_checks = [check for check in catalog.checks if isinstance(check, PytestCheck)]
        outcomes.update(self._run_pytest_checks(pytest_checks))
        for check in catalog.checks:
            if isinstance(check, CommandCheck):
                outcomes[check.id] = self._run_command_check(check)
            elif isinstance(check, ArtifactCheck):
                outcomes[check.id] = self._run_artifact_check(check)
            elif isinstance(check, FunctionCheck):
                outcomes[check.id] = self._run_function_check(check)
        return outcomes

    def _run_pytest_checks(self, checks: list[PytestCheck]) -> dict[str, CheckOutcome]:
        outcomes: dict[str, CheckOutcome] = {}
        batch = [check for check in checks if not check.isolated]
        isolated = [check for check in checks if check.isolated]
        outcomes.update(self._run_pytest_batch(batch, suffix=""))
        for check in isolated:
            outcomes.update(self._run_pytest_batch([check], suffix=f"-{check.id.replace('.', '_')}"))
        return outcomes

    def _run_pytest_batch(self, checks: list[PytestCheck], *, suffix: str) -> dict[str, CheckOutcome]:
        outcomes: dict[str, CheckOutcome] = {}
        if not checks:
            return outcomes
        ordered_targets: list[str] = []
        for check in checks:
            for target in check.targets:
                if target not in ordered_targets:
                    ordered_targets.append(target)
        missing = [target for target in ordered_targets if not (self.repo_root / target).exists()]
        valid_targets = [target for target in ordered_targets if target not in missing]
        junit_path = self.report_dir / f"pytest-junit{suffix}.xml"
        log_path = self.report_dir / f"pytest{suffix}.log"
        stats: dict[str, dict[str, int]] = {}
        run_detail = ""
        if valid_targets:
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                f"--junitxml={junit_path}",
                *valid_targets,
            ]
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.repo_root,
                    env=self.env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=PYTEST_TIMEOUT_SECONDS,
                    check=False,
                )
                duration = time.monotonic() - started
                run_detail = f"pytest exit {completed.returncode}"
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
                duration = time.monotonic() - started
                run_detail = f"pytest vượt timeout {PYTEST_TIMEOUT_SECONDS}s"
                log_path.write_text(run_detail, encoding="utf-8")
            if junit_path.is_file():
                try:
                    stats = _parse_junit(junit_path)
                except ET.ParseError as error:
                    run_detail += f"; junit parse lỗi: {error}"
        else:
            duration = 0.0
        for check in checks:
            missing_targets = [target for target in check.targets if target in missing]
            totals: dict[str, int] = {}
            detail_parts: list[str] = []
            ok = not missing_targets
            if missing_targets:
                detail_parts.append(f"target không tồn tại: {', '.join(missing_targets)}")
            for target in check.targets:
                if target in missing_targets:
                    continue
                target_ok, target_detail = _aggregate_stats(totals, target, stats)
                if not target_ok:
                    ok = False
                    detail_parts.append(target_detail)
            if ok:
                if totals.get("errors", 0) or totals.get("failed", 0):
                    ok = False
                    detail_parts.append(f"failed={totals.get('failed', 0)} errors={totals.get('errors', 0)}")
                elif totals.get("passed", 0) == 0:
                    ok = False
                    detail_parts.append(f"không có test passed (skipped={totals.get('skipped', 0)})")
                else:
                    detail_parts.append(
                        f"passed={totals.get('passed', 0)} skipped={totals.get('skipped', 0)} {run_detail}"
                    )
            outcomes[check.id] = CheckOutcome(
                check_id=check.id,
                kind="pytest",
                status="passed" if ok else "failed",
                detail="; ".join(detail_parts),
                duration_s=duration / max(len(checks), 1),
                evidence={"log": f"pytest{suffix}.log", "totals": totals, "targets": list(check.targets)},
            )
        return outcomes

    def _run_command_check(self, check: CommandCheck) -> CheckOutcome:
        executable = shutil.which(check.command[0])
        if executable is None:
            return CheckOutcome(check.id, "command", "failed", f"không tìm thấy lệnh {check.command[0]}", 0.0)
        command = [executable, *check.command[1:]]
        log_name = f"{check.id}.log"
        log_path = self.report_dir / log_name
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                env=self.env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - started
            log_path.write_text(f"timeout {COMMAND_TIMEOUT_SECONDS}s", encoding="utf-8")
            return CheckOutcome(check.id, "command", "failed", f"timeout {COMMAND_TIMEOUT_SECONDS}s", duration)
        duration = time.monotonic() - started
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
        ok = completed.returncode == 0
        return CheckOutcome(
            check_id=check.id,
            kind="command",
            status="passed" if ok else "failed",
            detail=f"exit {completed.returncode}",
            duration_s=duration,
            evidence={"command": list(check.command), "log": log_name},
        )

    def _run_artifact_check(self, check: ArtifactCheck) -> CheckOutcome:
        pattern = str(self.repo_root / check.path)
        candidates = sorted(
            (Path(item) for item in glob.glob(pattern, recursive=True)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return CheckOutcome(
                check_id=check.id,
                kind="artifact",
                status="not_run",
                detail=f"artifact chưa chạy: chạy {check.tool} để tạo {check.path}",
                duration_s=0.0,
            )
        latest = candidates[0]
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return CheckOutcome(check.id, "artifact", "failed", f"artifact không đọc được: {error}", 0.0)
        ok = payload.get("ok") is True
        tool = payload.get("tool", check.tool)
        detail = f"{latest.relative_to(self.repo_root)} tool={tool} ok={payload.get('ok')}"
        return CheckOutcome(
            check_id=check.id,
            kind="artifact",
            status="passed" if ok else "failed",
            detail=detail,
            duration_s=0.0,
            evidence={"artifact": str(latest.relative_to(self.repo_root)), "tool": tool},
        )

    def _run_function_check(self, check: FunctionCheck) -> CheckOutcome:
        started = time.monotonic()
        try:
            ok, detail = check.function(self.repo_root)
        except Exception as error:
            return CheckOutcome(
                check.id, "function", "failed", f"{type(error).__name__}: {error}", time.monotonic() - started
            )
        return CheckOutcome(
            check_id=check.id,
            kind="function",
            status="passed" if ok else "failed",
            detail=detail,
            duration_s=time.monotonic() - started,
        )


@dataclass
class ScenarioOutcome:
    scenario: Scenario
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.scenario.id,
            "title": self.scenario.title,
            "status": self.status,
            "business_effect": self.scenario.business_effect,
            "proof": self.scenario.proof,
            "denominator": self.scenario.denominator,
            "check_ids": list(self.scenario.check_ids),
            "requirement_refs": list(self.scenario.requirement_refs),
        }


@dataclass
class AcceptanceReport:
    run_id: str
    models: str
    filtered: bool
    started_at: str
    finished_at: str
    report_dir: str
    gaps: list[str]
    scenario_ids: tuple[str, ...]
    checks: dict[str, CheckOutcome]
    scenarios: list[ScenarioOutcome]
    ok: bool
    commit_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "models": self.models,
            "filtered": self.filtered,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_dir": self.report_dir,
            "commit_sha": self.commit_sha,
            "gaps": self.gaps,
            "scenario_ids": list(self.scenario_ids),
            "checks": {key: outcome.as_dict() for key, outcome in sorted(self.checks.items())},
            "scenarios": [outcome.as_dict() for outcome in self.scenarios],
            "ok": self.ok,
        }


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
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _aggregate_scenario(scenario: Scenario, outcomes: dict[str, CheckOutcome]) -> str:
    statuses: list[str] = []
    for check_id in scenario.check_ids:
        outcome = outcomes.get(check_id)
        statuses.append(outcome.status if outcome is not None else "not_run")
    if all(status == "passed" for status in statuses):
        return "passed"
    if any(status == "failed" for status in statuses):
        return "failed"
    return "not_run"


def run_catalog(
    catalog: Catalog,
    *,
    repo_root: Path,
    report_dir: Path,
    models: str = "fake",
    executor: CatalogExecutor | None = None,
    scenario_ids: tuple[str, ...] = (),
) -> AcceptanceReport:
    if models != "fake":
        raise ValueError(f"acceptance chỉ chạy với --models fake, nhận: {models}")
    started_at = now_iso()
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    run_dir = report_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    gaps = validate_catalog(catalog)
    filtered = bool(scenario_ids)
    selected = catalog
    if filtered:
        scenario_map = catalog.scenario_map()
        for scenario_id in scenario_ids:
            if scenario_id not in scenario_map:
                gaps.append(f"scenario filter không tồn tại: {scenario_id}")
        selected = catalog.subset_for_scenarios(scenario_ids)
    outcomes: dict[str, CheckOutcome] = {}
    if not gaps:
        active_executor: CatalogExecutor = executor or CatalogCommandExecutor(repo_root=repo_root, report_dir=run_dir)
        outcomes = active_executor.run(selected)
        for check in selected.checks:
            if check.id not in outcomes:
                outcomes[check.id] = CheckOutcome(
                    check_id=check.id,
                    kind=check_kind(check),
                    status="not_run",
                    detail="executor không trả kết quả cho check này",
                    duration_s=0.0,
                )
    scenario_outcomes = [
        ScenarioOutcome(scenario=scenario, status=_aggregate_scenario(scenario, outcomes))
        for scenario in selected.scenarios
    ]
    ok = not gaps and all(outcome.status == "passed" for outcome in scenario_outcomes)
    report = AcceptanceReport(
        run_id=run_id,
        models=models,
        filtered=filtered,
        started_at=started_at,
        finished_at=now_iso(),
        report_dir=str(run_dir),
        gaps=gaps,
        scenario_ids=tuple(scenario.id for scenario in selected.scenarios),
        checks=outcomes,
        scenarios=scenario_outcomes,
        ok=ok,
        commit_sha=_git_commit(repo_root),
    )
    payload = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    (run_dir / "report.json").write_text(payload + "\n", encoding="utf-8")
    if not filtered and not gaps:
        (report_dir / "latest.json").write_text(payload + "\n", encoding="utf-8")
    return report


@dataclass
class SummaryResult:
    ok: bool
    report_path: str
    gaps: list[str]
    scenarios: list[dict[str, Any]]
    workloads: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "report_path": self.report_path,
            "gaps": self.gaps,
            "scenarios": self.scenarios,
            "workloads": self.workloads,
        }


def summarize(*, repo_root: Path, report_dir: Path) -> SummaryResult:
    latest = report_dir / "latest.json"
    gaps: list[str] = []
    scenarios: list[dict[str, Any]] = []
    workloads: list[dict[str, Any]] = []
    if not latest.is_file():
        gaps.append("chưa có acceptance run đầy đủ (thiếu artifacts/acceptance/latest.json)")
        return SummaryResult(False, str(latest), gaps, scenarios, workloads)
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        gaps.append(f"latest.json không đọc được: {error}")
        return SummaryResult(False, str(latest), gaps, scenarios, workloads)
    if payload.get("filtered"):
        gaps.append("report mới nhất là lần chạy filter, không dùng làm bằng chứng đầy đủ")
    if payload.get("models") != "fake":
        gaps.append(f"models không hợp lệ: {payload.get('models')}")
    scenario_map = {item.get("id"): item for item in payload.get("scenarios", [])}
    checks = payload.get("checks", {})
    for scenario_id in (*EXPECTED_AC, *EXPECTED_NFR):
        item = scenario_map.get(scenario_id)
        if item is None:
            gaps.append(f"thiếu scenario trong report: {scenario_id}")
            continue
        if item.get("status") != "passed":
            gaps.append(f"scenario {scenario_id} trạng thái {item.get('status')}")
        missing_evidence = [
            check_id for check_id in item.get("check_ids", []) if checks.get(check_id, {}).get("status") != "passed"
        ]
        if missing_evidence:
            gaps.append(f"scenario {scenario_id} thiếu evidence: {', '.join(missing_evidence)}")
        scenarios.append(
            {
                "id": scenario_id,
                "status": item.get("status"),
                "check_ids": item.get("check_ids", []),
                "evidence": [checks.get(check_id, {}).get("evidence", {}) for check_id in item.get("check_ids", [])],
            }
        )
    workloads_root = repo_root / "artifacts" / "workloads"
    for profile in WORKLOAD_PROFILES:
        manifest_path = workloads_root / profile / "manifest.json"
        entry: dict[str, Any] = {"profile": profile, "manifest": str(manifest_path.relative_to(repo_root))}
        if not manifest_path.is_file():
            entry["ok"] = False
            entry["reason"] = "thiếu manifest"
            gaps.append(f"workload {profile}: thiếu manifest {manifest_path}")
            workloads.append(entry)
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            entry["ok"] = False
            entry["reason"] = f"manifest không đọc được: {error}"
            gaps.append(f"workload {profile}: manifest không đọc được")
            workloads.append(entry)
            continue
        entry.update(
            {
                "ok": manifest.get("ok") is True,
                "pinned_before_run": manifest.get("pinned_before_run") is True,
                "thresholds": manifest.get("thresholds", {}),
                "metrics_path": manifest.get("metrics_path"),
            }
        )
        if entry["ok"] is not True:
            gaps.append(f"workload {profile}: ok != true")
        if entry["pinned_before_run"] is not True:
            gaps.append(f"workload {profile}: thresholds chưa được pin trước khi chạy")
        if not entry["thresholds"]:
            gaps.append(f"workload {profile}: thiếu thresholds")
        metrics_path = manifest.get("metrics_path")
        generated_at = manifest.get("generated_at")
        if not metrics_path:
            gaps.append(f"workload {profile}: thiếu metrics_path")
        else:
            metrics_file = repo_root / metrics_path
            if not metrics_file.is_file():
                gaps.append(f"workload {profile}: thiếu metrics {metrics_path}")
            else:
                try:
                    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    gaps.append(f"workload {profile}: metrics không đọc được")
                else:
                    metrics_at = metrics.get("generated_at")
                    if not generated_at or not metrics_at or str(generated_at) > str(metrics_at):
                        gaps.append(f"workload {profile}: manifest không được pin trước khi đo")
        workloads.append(entry)
    return SummaryResult(not gaps, str(latest), gaps, scenarios, workloads)
