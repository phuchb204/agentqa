from __future__ import annotations

import time
import tracemalloc
from typing import Any

import yaml

from infra.workloads.common import DsnTable, WorkloadContext

CASE_FILE = "benchmarks/public/cases/taskboard/login_create_item.yaml"


async def run(ctx: WorkloadContext) -> dict[str, Any]:
    from tests.support.replay import build_replay_harness, seed_replay_workspace, submit_case_run
    from tests.support.taskboard import start_taskboard_server

    from agentqa.contracts.case import CaseContent
    from agentqa.platform.events.service import EventService
    from agentqa.platform.runs.read_models import RunReadModel
    from agentqa.platform.storage.roles import ROLE_API

    engines = ctx.engines
    user_id, workspace_id = await seed_replay_workspace(engines)
    namespace = "w1-personal"
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    with start_taskboard_server() as server:
        document = yaml.safe_load((ctx.repo_root / CASE_FILE).read_text(encoding="utf-8"))
        case = CaseContent.model_validate(document)
        harness = build_replay_harness(
            engines=engines,
            test_db=DsnTable(ctx.database),
            principal_id=user_id,
            workspace_id=workspace_id,
            taskboard_server=server,
        )
        try:
            tracemalloc.start()
            ids = await submit_case_run(
                engines,
                principal_id=user_id,
                workspace_id=workspace_id,
                case=case,
                environment_content={
                    "target_base_url": f"{server.base_url}/{namespace}",
                    "fixture_ref": "taskboard@1",
                    "namespace": namespace,
                    "parameters": {"item_name": "Việc workload W1"},
                },
            )
            started = time.monotonic()
            summaries = await harness.worker.run_until_idle()
            wall_seconds = time.monotonic() - started
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            verdict = summaries[0].verdict if summaries else None
            state = await RunReadModel(engines[ROLE_API]).run_state(
                workspace_id=workspace_id, principal_id=user_id, run_id=ids["run_id"]
            )
            events = await EventService(engines[ROLE_API]).query_durable(
                workspace_id=workspace_id,
                principal_id=user_id,
                run_id=ids["run_id"],
                limit=500,
            )
            probe: dict[str, Any] = {}
            for event in reversed(events):
                if event["type"] == "fixture.probed":
                    probe = event["summary"].get("probe", {})
                    break
            item_count = int(probe.get("item_count", -1))
            checks.append({"name": "correct_verdict", "ok": verdict == "passed", "detail": f"verdict={verdict}"})
            checks.append({"name": "correct_side_effect", "ok": item_count == 1, "detail": f"item_count={item_count}"})
            checks.append({"name": "trace_present", "ok": len(events) > 0, "detail": f"events={len(events)}"})
            checks.append(
                {
                    "name": "terminal_state",
                    "ok": state is not None and state.get("verdict") == "passed",
                    "detail": f"status={state.get('status') if state else None}",
                }
            )
            metrics = {
                "wall_seconds": wall_seconds,
                "tracemalloc_peak_bytes": peak_bytes,
                "events_count": len(events),
                "verdict": verdict,
                "item_count": item_count,
            }
        finally:
            harness.aclose()
    ok = (
        bool(checks)
        and all(check["ok"] for check in checks)
        and metrics.get("wall_seconds", 999) <= float(ctx.thresholds["max_wall_seconds"])
    )
    if metrics:
        metrics["max_wall_seconds"] = ctx.thresholds["max_wall_seconds"]
    return {"ok": ok, "checks": checks, "metrics": metrics}
