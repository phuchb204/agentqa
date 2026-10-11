from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

build_catalog = importlib.import_module("tools.acceptance.catalog").build_catalog
run_catalog = importlib.import_module("tools.acceptance.runner").run_catalog
summarize = importlib.import_module("tools.acceptance.runner").summarize


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="run_acceptance",
        description="Chạy acceptance catalog 24 AC + 12 NFR với evidence thật (models fake).",
    )
    parser.add_argument("--models", default="fake", choices=["fake"], help="model I/O luôn là fake trong acceptance")
    parser.add_argument(
        "--scenario", action="append", default=[], help="chỉ chạy scenario (dev); bỏ trống để chạy đầy đủ"
    )
    parser.add_argument("--canary-scan", action="store_true", help="scan synthetic canary trên safe sinks sau khi chạy")
    parser.add_argument("--summary", action="store_true", help="đọc acceptance run đầy đủ gần nhất và kiểm bằng chứng")
    parser.add_argument(
        "--report-dir", default="artifacts/acceptance", help="thư mục report (mặc định artifacts/acceptance)"
    )
    args = parser.parse_args(argv)

    report_dir = REPO_ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    if args.summary:
        result = summarize(repo_root=REPO_ROOT, report_dir=report_dir)
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    catalog = build_catalog()
    report = run_catalog(
        catalog,
        repo_root=REPO_ROOT,
        report_dir=report_dir,
        models=args.models,
        scenario_ids=tuple(args.scenario),
    )
    passed = sum(1 for outcome in report.scenarios if outcome.status == "passed")
    summary_line = {
        "run_id": report.run_id,
        "ok": report.ok,
        "filtered": report.filtered,
        "scenarios_passed": passed,
        "scenarios_total": len(report.scenarios),
        "checks": len(report.checks),
        "report": str(Path(report.report_dir) / "report.json"),
        "gaps": report.gaps,
    }
    print(json.dumps(summary_line, ensure_ascii=False, indent=2))
    if not report.ok:
        for outcome in report.scenarios:
            if outcome.status != "passed":
                failed_checks = [
                    f"{check_id}={report.checks[check_id].status}"
                    for check_id in outcome.scenario.check_ids
                    if check_id in report.checks and report.checks[check_id].status != "passed"
                ]
                print(f"[FAIL] {outcome.scenario.id} {outcome.status}: {', '.join(failed_checks)}", file=sys.stderr)

    exit_code = 0 if report.ok else 1
    if args.canary_scan and not report.filtered:
        try:
            from tools.acceptance.canary_scan import run_canary_scan
        except ImportError:
            print("[ERROR] canary scan chưa được triển khai (T3)", file=sys.stderr)
            return 2
        scan = run_canary_scan(repo_root=REPO_ROOT, run_dir=Path(report.report_dir))
        scan_path = Path(report.report_dir) / "canary-scan.json"
        scan_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"canary_scan": scan}, ensure_ascii=False, indent=2))
        if scan.get("ok") is not True:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
