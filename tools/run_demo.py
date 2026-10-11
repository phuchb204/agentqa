from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

run_demo = importlib.import_module("tools.demo.flow").run_demo


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="run_demo",
        description="Demo user flow end-to-end (synthetic applications/accounts, models fake).",
    )
    parser.add_argument("--models", default="fake", choices=["fake"], help="model I/O luôn là fake trong demo")
    parser.add_argument("--skip-build", action="store_true", help="không build lại web app trước khi chạy")
    parser.add_argument("--report-dir", default="artifacts/demo")
    args = parser.parse_args(argv)

    report_dir = REPO_ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = run_demo(build_web=not args.skip_build)
    stamped = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_path = report_dir / f"{stamped}.json"
    run_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (report_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "ok": report["ok"],
        "mode": report["mode"],
        "live_calls": report["live_calls"],
        "steps": [{"name": step["name"], "ok": step["ok"], "detail": step["detail"]} for step in report["steps"]],
        "report": str(run_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not report["ok"]:
        for step in report["steps"]:
            if not step["ok"]:
                print(f"[FAIL] {step['name']}: {step['detail']}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
