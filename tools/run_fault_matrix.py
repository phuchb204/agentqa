from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

run_matrix = importlib.import_module("tools.fault_matrix.runner").run_matrix


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="run_fault_matrix",
        description="Fault injection matrix tại submit/lease/admission/dispatch/Verify/DB/blob/finalization (fake).",
    )
    parser.add_argument("--models", default="fake", choices=["fake"], help="model I/O luôn là fake trong fault matrix")
    parser.add_argument("--report-dir", default="artifacts/faults", help="thư mục report (mặc định artifacts/faults)")
    args = parser.parse_args(argv)

    report_dir = REPO_ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = run_matrix(repo_root=REPO_ROOT, report_dir=report_dir, models=args.models)
    summary = {
        "run_id": report.run_id,
        "ok": report.ok,
        "cases_total": len(report.cases),
        "cases_passed": sum(1 for case in report.cases if case.status == "passed"),
        "report": str(Path(report.report_dir) / "report.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not report.ok:
        for case in report.cases:
            if case.status != "passed":
                print(f"[FAIL] {case.case_id} [{case.group}] {case.status}: {case.detail}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
