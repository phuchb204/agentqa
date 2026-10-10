from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
import yaml
from tests.support.platform import case_content
from tests.support.postgres import scoped_transaction, seed_execution, seed_run, seed_workspace
from tests.support.replay import build_replay_harness, seed_replay_workspace, submit_case_run
from tests.support.taskboard import TaskboardServer

from agentqa.contracts.case import CaseContent
from agentqa.platform.fixtures import FixtureRegistry, TaskboardFixture
from agentqa.platform.fixtures.runs import FixtureRunService
from agentqa.platform.runs.coordinator import ExecutionSpec, RunCoordinator, RunEventRecorder
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_SUPERVISOR

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"


async def _fixture_rows(engines, *, workspace_id, principal_id):
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        return (
            await session.execute(
                sa.select(
                    tables.fixture_runs.c.action,
                    tables.fixture_runs.c.state,
                    tables.fixture_runs.c.attempts,
                    tables.fixture_runs.c.detail,
                ).order_by(tables.fixture_runs.c.created_at, tables.fixture_runs.c.id)
            )
        ).all()


async def test_lifecycle_records_prepare_reset_cleanup(role_engines, fixture_registry, taskboard_server) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"fixture-{uuid4().hex[:8]}")
    service = FixtureRunService(engines[ROLE_SUPERVISOR], registry=fixture_registry)
    namespace = "life-cycle"
    prepare = fixture_registry.prepare("taskboard@1", namespace)
    assert prepare.ok
    await service.record_lifecycle(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        receipt=prepare,
    )
    reset = fixture_registry.reset("taskboard@1", namespace)
    assert reset.ok
    await service.record_lifecycle(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        receipt=reset,
    )
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["item_count"] == 0
    record_id = await service.enqueue_cleanup(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        fixture_ref="taskboard@1",
        namespace=namespace,
    )
    duplicate = await service.enqueue_cleanup(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        fixture_ref="taskboard@1",
        namespace=namespace,
    )
    assert duplicate != record_id
    results = await service.process_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="fixture-worker", limit=5
    )
    mine = [item for item in results if item["record_id"] in (record_id, duplicate)]
    assert mine
    assert all(item["state"] == "succeeded" for item in mine)
    assert any(item["attempts"] == 1 for item in mine)

    rows = await _fixture_rows(engines, workspace_id=workspace_id, principal_id=user_id)
    by_action = {row.action: row for row in rows}
    assert by_action["prepare"].state == "succeeded"
    assert by_action["reset"].state == "succeeded"
    assert by_action["cleanup"].state == "succeeded"
    detail_text = json.dumps(by_action["prepare"].detail, ensure_ascii=False)
    assert "fixture_digest" in detail_text
    assert "tb-" not in detail_text


async def test_setup_failure_blocks_case_without_actions(role_engines, fixture_registry) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"fixture-{uuid4().hex[:8]}")
    run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id)
    execution_id = await seed_execution(
        engines, principal_id=user_id, workspace_id=workspace_id, run_id=run_id, logical_key="fx-fail"
    )
    service = FixtureRunService(engines[ROLE_SUPERVISOR], registry=fixture_registry)
    coordinator = RunCoordinator(
        runtime=None,
        contexts=None,
        read_port=None,
        scene_provider=None,
        fixtures=fixture_registry,
        recorder=RunEventRecorder(engines[ROLE_API]),
        fixture_runs=service,
    )
    spec = ExecutionSpec(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=run_id,
        execution_id=execution_id,
        attempt_id=execution_id,
        logical_key="fx-fail",
        case=CaseContent.model_validate(case_content()),
        target_base_url="http://127.0.0.1:1",
        fixture_ref="ghost@1",
        namespace="ghost-namespace",
    )
    outcome = await coordinator.execute(spec)
    assert outcome.status == "error"
    assert outcome.verdict == "inconclusive"
    assert outcome.reasons == ["fixture_failed"]
    assert outcome.steps == []
    assert outcome.trace_refs == []
    rows = await _fixture_rows(engines, workspace_id=workspace_id, principal_id=user_id)
    assert len(rows) == 1
    assert rows[0].action == "prepare"
    assert rows[0].state == "failed"
    assert rows[0].attempts == 1


async def test_cleanup_retries_bounded_then_exhausted(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"fixture-{uuid4().hex[:8]}")
    broken_registry = FixtureRegistry()
    broken_registry.register(TaskboardFixture("http://127.0.0.1:1", "token-khong-dung"))
    service = FixtureRunService(engines[ROLE_SUPERVISOR], registry=broken_registry, max_attempts=3, backoff_seconds=0)
    record_id = await service.enqueue_cleanup(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        fixture_ref="taskboard@1",
        namespace="cleanup-broken",
    )
    states = []
    for _ in range(4):
        results = await service.process_due(
            workspace_id=workspace_id, principal_id=user_id, worker_id="fixture-worker", limit=1
        )
        states.append([item["state"] for item in results])
    assert states[0] == ["pending"]
    assert states[1] == ["pending"]
    assert states[2] == ["exhausted"]
    assert states[3] == []
    rows = await _fixture_rows(engines, workspace_id=workspace_id, principal_id=user_id)
    record = next(row for row in rows if row.action == "cleanup")
    assert record.state == "exhausted"
    assert record.attempts == 3
    assert record_id is not None


async def test_business_failure_survives_successful_cleanup(
    role_engines, test_db, taskboard_server: TaskboardServer, fixture_registry
) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_replay_workspace(engines)
    harness = build_replay_harness(
        engines=engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
    )
    try:
        document = yaml.safe_load((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
        document["nodes"][-1]["assertions"][0]["expected"]["value"] = 2
        case = CaseContent.model_validate(document)
        namespace = "fx-business-fail"
        ids = await submit_case_run(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            case=case,
            environment_content={
                "target_base_url": f"{taskboard_server.base_url}/{namespace}",
                "fixture_ref": "taskboard@1",
                "namespace": namespace,
                "parameters": {"item_name": "Việc lỗi nghiệp vụ"},
            },
        )
        summaries = await harness.worker.run_until_idle()
        assert len(summaries) == 1
        assert summaries[0].verdict == "failed"

        from agentqa.platform.runs.read_models import RunReadModel

        state = await RunReadModel(engines[ROLE_API]).run_state(
            workspace_id=workspace_id, principal_id=user_id, run_id=ids["run_id"]
        )
        assert state is not None
        assert state["verdict"] == "failed"
        assert "cleanup_failed" not in state["reasons"]

        rows = await _fixture_rows(engines, workspace_id=workspace_id, principal_id=user_id)
        execution_rows = [row for row in rows]
        actions = {(row.action, row.state) for row in execution_rows}
        assert ("prepare", "succeeded") in actions
        assert ("cleanup", "succeeded") in actions
    finally:
        harness.aclose()
