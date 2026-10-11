from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

run_scenario = importlib.import_module("tools.ui_harness.runner").run_scenario

SCENARIOS = ("authoring", "live", "healing", "reporting", "experiments", "admin")
REPORT_DIR = REPO_ROOT / "artifacts" / "ui-e2e"


def _ensure_dist() -> None:
    dist = REPO_ROOT / "apps" / "web" / "dist" / "index.html"
    if dist.is_file():
        return
    subprocess.run(
        ["pnpm", "--dir", "apps/web", "build"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        shell=sys.platform == "win32",
    )


def _run_one(name: str) -> dict:
    report = run_scenario(scenario=name, build_web=False)
    payload = report.as_dict()
    payload["scenario"] = name
    return payload


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_ui_e2e", description="UI E2E harness với API/DB/browser thật")
    parser.add_argument("--models", default="fake", choices=["fake"], help="model I/O luôn là fake trong harness")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=[*SCENARIOS, "all"],
    )
    parser.add_argument("--skip-build", action="store_true", help="không build lại web app trước khi chạy")
    args = parser.parse_args(argv)

    names = SCENARIOS if args.scenario == "all" else (args.scenario,)
    if not args.skip_build:
        _ensure_dist()
    results = [_run_one(name) for name in names]
    ok = all(bool(item["ok"]) for item in results)
    artifact = {
        "schema_version": "ui-e2e-report/1",
        "tool": "run_ui_e2e",
        "models": args.models,
        "ok": ok,
        "scenarios": [
            {
                "name": item["scenario"],
                "ok": item["ok"],
                "run_verdict": item.get("run_verdict"),
                "error": item.get("error"),
                "checks": item.get("checks", []),
            }
            for item in results
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "ok": ok,
        "scenarios": {item["scenario"]: item["ok"] for item in results},
        "checks": sum(len(item.get("checks", [])) for item in results),
        "report": str(REPORT_DIR / "latest.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not ok:
        for item in results:
            if not item["ok"]:
                print(f"[FAIL] {item['scenario']}: {item.get('error')}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
