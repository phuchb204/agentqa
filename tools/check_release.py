from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

build_sbom = importlib.import_module("tools.release.sbom").build_sbom
validate_release = importlib.import_module("tools.release.validation").validate_release


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _schemas_digest(repo_root: Path) -> str | None:
    schemas_dir = repo_root / "schemas"
    if not schemas_dir.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(schemas_dir.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(repo_root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_sha(repo_root: Path) -> str | None:
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


def _product_metadata(repo_root: Path) -> dict:
    pyproject = repo_root / "pyproject.toml"
    version = None
    requires = None
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        version = project.get("version")
        requires = project.get("requires-python")
    node_engine = None
    web_package = repo_root / "apps" / "web" / "package.json"
    if web_package.is_file():
        try:
            node_engine = json.loads(web_package.read_text(encoding="utf-8")).get("engines", {}).get("node")
        except json.JSONDecodeError:
            node_engine = None
    return {"name": "AgentQA", "version": version, "python_requires": requires, "node_engine": node_engine}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="check_release",
        description="Kiểm release: receipts, schema/locks/build digests, G0-G8, live receipts, calibration, SBOM.",
    )
    parser.add_argument("--check", action="store_true", help="chạy full structural check (bao gồm schema export gate)")
    parser.add_argument("--no-write", action="store_true", help="không ghi release bundle")
    parser.add_argument("--report-dir", default="artifacts/release")
    args = parser.parse_args(argv)

    report = validate_release(REPO_ROOT, run_schema_gate=True)
    report_dir = REPO_ROOT / args.report_dir
    manifest: dict = {}
    if not args.no_write:
        report_dir.mkdir(parents=True, exist_ok=True)
        sbom = build_sbom(REPO_ROOT)
        (report_dir / "sbom.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validation_path = report_dir / "validation.json"
        validation_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dist_index = REPO_ROOT / "apps" / "web" / "dist" / "index.html"
        manifest = {
            "schema_version": "release-manifest/1",
            "tool": "check_release",
            "generated_at": datetime.now(UTC).isoformat(),
            "product": _product_metadata(REPO_ROOT),
            "commit_sha": _git_sha(REPO_ROOT),
            "digests": {
                "uv_lock": _sha256(REPO_ROOT / "uv.lock"),
                "pnpm_lock": _sha256(REPO_ROOT / "pnpm-lock.yaml"),
                "schemas": _schemas_digest(REPO_ROOT),
                "web_dist": _sha256(dist_index),
            },
            "sbom": "artifacts/release/sbom.json",
            "validation": "artifacts/release/validation.json",
            "full_release": report.full_release,
            "reasons": report.reasons,
        }
        (report_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary = {
        "structural_ok": report.structural_ok,
        "full_release": report.full_release,
        "reasons": report.reasons,
        "provisional": report.provisional,
        "coverage": {
            "fr_covered": len(report.coverage["fr"]),
            "fr_missing": report.coverage["fr_missing"],
            "ac": len(report.coverage["ac"]),
            "nfr": len(report.coverage["nfr"]),
        },
        "gates": {gate: report.gates[gate]["ok"] for gate in ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")},
        "live_receipts": report.live_receipts,
        "manifest": str(report_dir / "manifest.json") if manifest else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not report.structural_ok:
        for check in report.checks:
            if not check.ok:
                print(f"[FAIL] {check.id}: {check.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
