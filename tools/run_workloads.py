from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_EXTRA_PATHS = (
    "benchmarks/apps/taskboard",
    "benchmarks/apps/shopflow",
    "benchmarks/apps/canvasdesk",
    "benchmarks/private",
)
for _extra in _EXTRA_PATHS:
    _extra_path = str(REPO_ROOT / _extra)
    if _extra_path not in sys.path:
        sys.path.insert(0, _extra_path)

PROFILE_MODULES = {
    "W1": "infra.workloads.w1_personal",
    "W2": "infra.workloads.w2_shared",
    "W3": "infra.workloads.w3_events",
    "W4": "infra.workloads.w4_history",
    "W5": "infra.workloads.w5_recovery",
    "W6": "infra.workloads.w6_isolation",
}


def _profile_config(profile: str) -> dict:
    configs = {
        "W1": {"workers": 1, "executions": 1, "fixture": "taskboard deterministic"},
        "W2": {"workers": 6, "executions": 32, "fake_model_latency_seconds": 0.25},
        "W3": {"read_clients": 20, "executions": 2, "events_per_execution": 2000, "reconnecting_clients": 5},
        "W4": {"records": 10000, "page_size": 50},
        "W5": {"fault_rounds": 3},
        "W6": {"namespaces": 2, "restore_exercise": True},
    }
    return configs[profile]


async def _run_profile(profile: str, report_dir: Path) -> dict:
    from infra.workloads import common

    profile_dir = report_dir / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    database, engines = await common.setup_engines()
    ctx = common.WorkloadContext(
        repo_root=REPO_ROOT,
        profile=profile,
        profile_dir=profile_dir,
        database=database,
        engines=engines,
        thresholds=common.DEFAULT_THRESHOLDS[profile],
        config=_profile_config(profile),
        started_monotonic=time.monotonic(),
    )
    await common.pin_manifest(ctx)
    result: dict = {"profile": profile, "ok": False, "checks": [], "metrics": {}}
    try:
        module = importlib.import_module(PROFILE_MODULES[profile])
        outcome = await module.run(ctx)
        metrics = common.write_metrics(ctx, {"checks": outcome.get("checks", []), **outcome.get("metrics", {})})
        common.finalize_manifest(
            ctx,
            ok=bool(outcome.get("ok")),
            extra={"checks": outcome.get("checks", [])},
        )
        result = {
            "profile": profile,
            "ok": bool(outcome.get("ok")),
            "checks": outcome.get("checks", []),
            "metrics": metrics,
        }
    except Exception as error:
        common.write_failure_artifact(ctx, error)
        common.finalize_manifest(ctx, ok=False, extra={"error": f"{type(error).__name__}: {error}"})
        result = {
            "profile": profile,
            "ok": False,
            "checks": [],
            "metrics": {},
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        await common.close_engines(engines, database)
    return result


def _run_async(coro):
    from agentqa.platform.storage.database import configure_event_loop_policy

    configure_event_loop_policy()
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="run_workloads",
        description="Chạy workload W1-W6 với manifests pin trước, raw metrics và thresholds (models fake).",
    )
    parser.add_argument("--models", default="fake", choices=["fake"])
    parser.add_argument("--profile", default="all", choices=[*PROFILE_MODULES, "all"])
    parser.add_argument("--report-dir", default="artifacts/workloads")
    args = parser.parse_args(argv)

    report_dir = REPO_ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    profiles = list(PROFILE_MODULES) if args.profile == "all" else [args.profile]
    results = [_run_async(_run_profile(profile, report_dir)) for profile in profiles]
    latest = __import__("infra.workloads.common", fromlist=["update_latest"]).update_latest(
        report_dir, REPO_ROOT, results
    )
    summary = {
        "ok": all(result["ok"] for result in results) and latest["ok"]
        if args.profile == "all"
        else all(result["ok"] for result in results),
        "profiles": {result["profile"]: result["ok"] for result in results},
        "latest": latest,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        for result in results:
            if not result["ok"]:
                print(f"[FAIL] {result['profile']}: {result.get('error') or result.get('checks')}", file=sys.stderr)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
