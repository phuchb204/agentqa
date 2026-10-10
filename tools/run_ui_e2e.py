from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

run_scenario = importlib.import_module("tools.ui_harness.runner").run_scenario


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_ui_e2e", description="UI E2E harness với API/DB/browser thật")
    parser.add_argument("--models", default="fake", choices=["fake"], help="model I/O luôn là fake trong harness")
    parser.add_argument("--scenario", default="authoring", choices=["authoring", "live", "healing", "reporting"])
    parser.add_argument("--skip-build", action="store_true", help="không build lại web app trước khi chạy")
    args = parser.parse_args(argv)

    report = run_scenario(scenario=args.scenario, build_web=not args.skip_build)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if report.error:
        print(f"[ERROR] {report.error}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
