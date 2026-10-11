from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.release.sbom import build_sbom

VALIDATION_SCHEMA_VERSION = "release-validation/1"
FALSE_HEAL_CEILING = 0.01
EXPECTED_AC = tuple(f"AC-{index:02d}" for index in range(1, 25))
EXPECTED_NFR = tuple(f"NFR-{index:02d}" for index in range(1, 13))
FR_IDS = tuple(f"FR-{index:02d}" for index in range(1, 52))
WORKLOAD_PROFILES = ("W1", "W2", "W3", "W4", "W5", "W6")
UI_SCENARIOS = ("authoring", "live", "healing", "reporting", "experiments", "admin")
GATE_TASKS = {
    "G0": "P01-P03",
    "G1": "P04-P06",
    "G2": "P07-P11",
    "G3": "P12-P15",
    "G4": "P16-P19",
    "G5": "P20-P22",
    "G6": "P23-P26",
    "G7": "P27-P30",
    "G8": "P31-P32",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass
class ReleaseCheck:
    id: str
    ok: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "ok": self.ok, "detail": self.detail, "evidence": self.evidence}


@dataclass
class ReleaseReport:
    checks: list[ReleaseCheck]
    readiness: list[ReleaseCheck]
    gates: dict[str, dict[str, Any]]
    coverage: dict[str, Any]
    live_receipts: list[dict[str, Any]]
    provisional: list[str]
    reasons: list[str]
    full_release: bool
    sbom: dict[str, Any]
    generated_at: str = field(default_factory=_now_iso)

    @property
    def structural_ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "tool": "check_release",
            "generated_at": self.generated_at,
            "structural_ok": self.structural_ok,
            "full_release": self.full_release,
            "reasons": self.reasons,
            "provisional": self.provisional,
            "checks": [check.as_dict() for check in self.checks],
            "readiness": [check.as_dict() for check in self.readiness],
            "gates": self.gates,
            "coverage": self.coverage,
            "live_receipts": self.live_receipts,
            "sbom": {
                "schema_version": self.sbom.get("schema_version"),
                "counts": self.sbom.get("counts"),
                "sources": self.sbom.get("sources"),
            },
        }


def _latest_model_receipt(repo_root: Path, route: str) -> dict | None:
    files = sorted(
        (repo_root / "artifacts" / "model-capabilities").glob(f"{route}-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None
    payload = _load_json(files[0])
    if payload is None:
        return None
    payload["_path"] = files[0].relative_to(repo_root).as_posix()
    return payload


def _receipt_expired(receipt: dict) -> bool:
    expires = receipt.get("expires_at")
    if not isinstance(expires, str):
        return True
    try:
        moment = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return True
    return moment < datetime.now(UTC)


def _latest_calibration_receipt(repo_root: Path) -> dict | None:
    files = sorted(
        (repo_root / "artifacts" / "calibration").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None
    payload = _load_json(files[0])
    if payload is None:
        return None
    payload["_path"] = files[0].relative_to(repo_root).as_posix()
    return payload


def _check_acceptance(repo_root: Path) -> tuple[ReleaseCheck, dict | None]:
    report = _load_json(repo_root / "artifacts" / "acceptance" / "latest.json")
    if report is None:
        return ReleaseCheck("acceptance", False, "thiếu artifacts/acceptance/latest.json"), None
    scenario_ids = {item.get("id") for item in report.get("scenarios", [])}
    expected = set(EXPECTED_AC) | set(EXPECTED_NFR)
    ok = report.get("ok") is True and expected <= scenario_ids
    missing = sorted(expected - scenario_ids)
    return (
        ReleaseCheck(
            "acceptance",
            ok,
            f"ok={report.get('ok')} scenarios={len(scenario_ids)} missing={missing[:5]}",
            {"report": "artifacts/acceptance/latest.json", "run_id": report.get("run_id")},
        ),
        report,
    )


def _coverage(repo_root: Path, acceptance: dict | None) -> dict[str, Any]:
    if acceptance is None:
        return {"fr": [], "fr_missing": list(FR_IDS), "ac": [], "nfr": []}
    scenario_ids = {item.get("id") for item in acceptance.get("scenarios", [])}
    fr_covered: set[str] = set()
    try:
        import importlib

        catalog = importlib.import_module("tools.acceptance.catalog").build_catalog()
        for scenario in catalog.scenarios:
            if scenario.id in scenario_ids:
                fr_covered.update(ref for ref in scenario.requirement_refs if ref.startswith("FR-"))
    except Exception:
        fr_covered = set()
    return {
        "fr": sorted(fr_covered),
        "fr_missing": sorted(set(FR_IDS) - fr_covered),
        "ac": sorted(scenario_ids & set(EXPECTED_AC)),
        "nfr": sorted(scenario_ids & set(EXPECTED_NFR)),
    }


def _gates(
    *,
    acceptance_ok: bool,
    faults_ok: bool,
    ui_ok: bool,
    os_ok: bool,
    workloads_ok: bool,
    schemas_ok: bool,
    live_ok: bool,
    research_ok: bool,
) -> dict[str, dict[str, Any]]:
    def gate(ok: bool, evidence: list[str]) -> dict[str, Any]:
        return {"ok": ok, "evidence": evidence}

    return {
        "G0": gate(schemas_ok, ["artifacts/acceptance checks cmd.nfr10.*", "tests/contracts + migrations"]),
        "G1": gate(acceptance_ok, ["acceptance NFR-03/AC-20", "database/test_rls"]),
        "G2": gate(acceptance_ok and faults_ok, ["acceptance AC-01..AC-12", "artifacts/faults/latest.json"]),
        "G3": gate(acceptance_ok and live_ok, ["acceptance AC-13/14", "artifacts/model-capabilities/*"]),
        "G4": gate(acceptance_ok and ui_ok, ["acceptance AC-01..AC-05/22", "artifacts/ui-e2e/latest.json"]),
        "G5": gate(acceptance_ok, ["acceptance AC-08..AC-16/19", "tests/verify + tests/agent"]),
        "G6": gate(acceptance_ok and os_ok, ["acceptance AC-18/22/23", "artifacts/os-smoke/latest.json"]),
        "G7": gate(acceptance_ok and research_ok, ["acceptance AC-21", "artifacts/research + tests/experiments"]),
        "G8": gate(acceptance_ok and faults_ok and ui_ok and os_ok and workloads_ok, ["P31 aggregate receipts"]),
        "tasks": GATE_TASKS,
    }


def validate_release(
    repo_root: Path,
    *,
    run_schema_gate: bool = False,
    require_p32: bool = True,
) -> ReleaseReport:
    checks: list[ReleaseCheck] = []
    reasons: list[str] = []
    provisional: list[str] = []

    acceptance_check, acceptance = _check_acceptance(repo_root)
    checks.append(acceptance_check)

    faults = _load_json(repo_root / "artifacts" / "faults" / "latest.json")
    faults_ok = bool(faults) and faults.get("ok") is True and faults.get("cases_passed") == faults.get("cases_total")
    checks.append(
        ReleaseCheck(
            "fault_matrix",
            faults_ok,
            f"ok={faults.get('ok') if faults else None} cases={faults.get('cases_passed') if faults else 0}",
            {"report": "artifacts/faults/latest.json"},
        )
    )

    ui = _load_json(repo_root / "artifacts" / "ui-e2e" / "latest.json")
    ui_scenarios = ui.get("scenarios", []) if ui else []
    ui_names = {item.get("name") for item in ui_scenarios}
    ui_ok = bool(ui) and ui.get("ok") is True and set(UI_SCENARIOS) <= ui_names
    checks.append(ReleaseCheck("ui_e2e", ui_ok, f"ok={ui.get('ok') if ui else None} scenarios={sorted(ui_names)}"))

    os_smoke = _load_json(repo_root / "artifacts" / "os-smoke" / "latest.json")
    os_profiles = os_smoke.get("profiles", {}) if os_smoke else {}
    os_ok = (
        bool(os_smoke)
        and os_smoke.get("ok") is True
        and os_profiles.get("windows", {}).get("ok") is True
        and os_profiles.get("linux", {}).get("ok") is True
    )
    checks.append(
        ReleaseCheck("os_smoke", os_ok, f"ok={os_smoke.get('ok') if os_smoke else None} profiles={sorted(os_profiles)}")
    )

    workloads = _load_json(repo_root / "artifacts" / "workloads" / "latest.json")
    workloads_profiles = workloads.get("profiles", {}) if workloads else {}
    workloads_ok = bool(workloads) and workloads.get("ok") is True and set(WORKLOAD_PROFILES) <= set(workloads_profiles)
    checks.append(
        ReleaseCheck(
            "workloads",
            workloads_ok,
            f"ok={workloads.get('ok') if workloads else None} profiles={sorted(workloads_profiles)}",
        )
    )

    web_tests = _load_json(repo_root / "artifacts" / "web-tests" / "latest.json")
    web_ok = bool(web_tests) and web_tests.get("ok") is True
    checks.append(ReleaseCheck("web_tests", web_ok, f"ok={web_tests.get('ok') if web_tests else None}"))

    schemas_ok = True
    if run_schema_gate:
        completed = subprocess.run(
            ["uv", "run", "--locked", "python", "tools/export_schemas.py", "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=600,
        )
        schemas_ok = completed.returncode == 0
        checks.append(
            ReleaseCheck(
                "schema_export",
                schemas_ok,
                (completed.stdout or completed.stderr or "").strip().splitlines()[-1]
                if completed.stdout or completed.stderr
                else "",
            )
        )
    else:
        checks.append(
            ReleaseCheck(
                "schema_export",
                True,
                "skipped (unit mode); CLI --check chạy export_schemas --check",
                {"skipped": True},
            )
        )

    uv_lock = repo_root / "uv.lock"
    pnpm_lock = repo_root / "pnpm-lock.yaml"
    lock_ok = uv_lock.is_file() and pnpm_lock.is_file()
    checks.append(
        ReleaseCheck(
            "lock_digests",
            lock_ok,
            f"uv.lock={_sha256(uv_lock)} pnpm-lock={_sha256(pnpm_lock)}",
        )
    )

    dist_index = repo_root / "apps" / "web" / "dist" / "index.html"
    wheel_files = sorted((repo_root / "dist").glob("agentqa-*.whl")) if (repo_root / "dist").is_dir() else []
    build_ok = dist_index.is_file()
    checks.append(
        ReleaseCheck(
            "build_digests",
            build_ok,
            f"web_dist={_sha256(dist_index)} wheel={_sha256(wheel_files[0]) if wheel_files else None}",
        )
    )

    live_receipts: list[dict[str, Any]] = []
    live_present = True
    live_valid = True
    for route, required_text in (("opencode_go", "verified"), ("opencode_zen", "verified")):
        receipt = _latest_model_receipt(repo_root, route)
        if receipt is None:
            live_present = False
            live_valid = False
            live_receipts.append({"route": route, "ok": False, "reason": "missing_receipt"})
            reasons.append(f"live receipt thiếu cho {route}")
            continue
        expired = _receipt_expired(receipt)
        text_ok = receipt.get("capabilities", {}).get("text") == required_text
        image_state = receipt.get("capabilities", {}).get("image")
        entry_ok = text_ok and not expired
        live_valid = live_valid and entry_ok
        if expired:
            reasons.append(f"live receipt {route} hết hạn ({receipt.get('expires_at')})")
        if not text_ok:
            reasons.append(f"live receipt {route} text != verified")
        live_receipts.append(
            {
                "route": route,
                "ok": entry_ok,
                "path": receipt.get("_path"),
                "expires_at": receipt.get("expires_at"),
                "capabilities": receipt.get("capabilities"),
                "image_state": image_state,
                "version_identity": receipt.get("version_identity"),
            }
        )
    checks.append(ReleaseCheck("live_receipts", live_present, f"routes={len(live_receipts)} present={live_present}"))

    calibration = _latest_calibration_receipt(repo_root)
    calibration_provisional = True
    calibration_detail = "thiếu receipt calibration"
    if calibration is not None:
        bound = float(calibration.get("bound_upper", 1.0))
        evidence = calibration.get("evidence")
        calibration_provisional = bound > FALSE_HEAL_CEILING or evidence != "measured"
        calibration_detail = f"bound_upper={bound} ceiling={FALSE_HEAL_CEILING} evidence={evidence}"
    if calibration_provisional:
        provisional.append("calibration_healing_profile")
        reasons.append(f"production healing profile provisional: {calibration_detail}")
    checks.append(ReleaseCheck("calibration", calibration is not None, calibration_detail))

    research_ok = False
    research_root = repo_root / "artifacts" / "research"
    if research_root.is_dir():
        research_ok = any(path.is_dir() for path in research_root.iterdir())
    checks.append(ReleaseCheck("research_bundles", research_ok, f"bundles={research_ok}"))

    p32_ok = True
    if require_p32:
        runbooks = [
            "docs/runbooks/quickstart.md",
            "docs/runbooks/demo.md",
            "docs/runbooks/research-reproduction.md",
            "docs/runbooks/release-validation.md",
        ]
        missing = [item for item in runbooks if not (repo_root / item).is_file()]
        if not (repo_root / "CHANGELOG.md").is_file():
            missing.append("CHANGELOG.md")
        p32_ok = not missing
        if missing:
            reasons.append(f"P32 artifacts thiếu: {', '.join(missing)}")
    readiness = [
        ReleaseCheck("p32_artifacts", p32_ok, "runbooks + CHANGELOG present"),
        ReleaseCheck("live_receipts_valid", live_valid, "Go/Zen receipts còn hạn và verified"),
        ReleaseCheck("calibration_not_provisional", not calibration_provisional, calibration_detail),
    ]

    sbom = build_sbom(repo_root)
    sbom_ok = sbom["counts"]["pypi"] > 0 and sbom["counts"]["npm"] > 0
    checks.append(ReleaseCheck("sbom", sbom_ok, f"counts={sbom['counts']}"))

    coverage = _coverage(repo_root, acceptance if isinstance(acceptance, dict) else None)
    readiness.append(
        ReleaseCheck(
            "coverage_complete",
            not coverage["fr_missing"],
            f"fr_missing={coverage['fr_missing'][:8]}",
        )
    )
    gates = _gates(
        acceptance_ok=acceptance_check.ok,
        faults_ok=faults_ok,
        ui_ok=ui_ok,
        os_ok=os_ok,
        workloads_ok=workloads_ok,
        schemas_ok=schemas_ok,
        live_ok=live_valid,
        research_ok=research_ok,
    )
    full_release = all(check.ok for check in checks) and all(check.ok for check in readiness)
    if coverage["fr_missing"]:
        reasons.append(f"FR chưa có scenario phủ: {coverage['fr_missing'][:8]}")
    if not full_release and not reasons:
        reasons.append("một hoặc nhiều structural/readiness checks chưa đạt")
    return ReleaseReport(
        checks=checks,
        readiness=readiness,
        gates=gates,
        coverage=coverage,
        live_receipts=live_receipts,
        provisional=provisional,
        reasons=reasons,
        full_release=full_release,
        sbom=sbom,
    )
