from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentqa.contracts.case import CaseContent
from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.artifacts.store import FaultBlobStore
from agentqa.platform.events.service import EventService
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage.roles import ROLE_API
from tests.support.replay import build_replay_harness, seed_replay_workspace, submit_case_run
from tests.support.taskboard import TaskboardServer

pytestmark = pytest.mark.asyncio

CASE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "public" / "cases" / "taskboard"


async def test_failed_blob_write_keeps_unavailable_record_with_zero_blobs(fault_env, tmp_path: Path) -> None:
    env = fault_env
    store = FaultBlobStore(tmp_path / "faulty-blobs", fail_on_write=True)
    service = ArtifactService(env.engines[ROLE_API], store)
    view = await service.stage(
        workspace_id=env.workspace_id,
        principal_id=env.user_id,
        kind="evidence",
        media_type="image/png",
        payload=b"partial-evidence-bytes",
        run_id=env.run_id,
    )
    assert view.state == "unavailable"
    assert view.unavailable_reason == "blob_write_failed"
    assert view.digest is None
    assert view.object_key is not None

    refetched = await service.get_authorized(
        workspace_id=env.workspace_id, principal_id=env.user_id, artifact_id=view.id
    )
    assert refetched.state == "unavailable"
    with pytest.raises(IdentityError):
        await service.open_bytes(workspace_id=env.workspace_id, principal_id=env.user_id, artifact_id=view.id)

    report = await service.reconcile(workspace_id=env.workspace_id, principal_id=env.user_id)
    assert report.scanned == 0
    after = await service.get_authorized(workspace_id=env.workspace_id, principal_id=env.user_id, artifact_id=view.id)
    assert after.state == "unavailable"
    assert after.unavailable_reason == "blob_write_failed"

    blob_files = [path for path in store.root.rglob("*") if path.is_file()]
    assert blob_files == []


async def test_storage_fault_keeps_partial_trace_without_false_pass(
    role_engines, test_db, taskboard_server: TaskboardServer
) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_replay_workspace(engines)
    harness = build_replay_harness(
        engines=engines,
        test_db=test_db,
        principal_id=user_id,
        workspace_id=workspace_id,
        taskboard_server=taskboard_server,
        fault_storage=True,
    )
    try:
        document = yaml.safe_load((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
        case = CaseContent.model_validate(document)
        namespace = "partial-artifact"
        ids = await submit_case_run(
            engines,
            principal_id=user_id,
            workspace_id=workspace_id,
            case=case,
            environment_content={
                "target_base_url": f"{taskboard_server.base_url}/{namespace}",
                "fixture_ref": "taskboard@1",
                "namespace": namespace,
                "parameters": {"item_name": "Việc evidence lỗi"},
            },
        )
        summaries = await harness.worker.run_until_idle()
        assert len(summaries) == 1
        assert summaries[0].verdict != "passed"

        state = await RunReadModel(engines[ROLE_API]).run_state(
            workspace_id=workspace_id, principal_id=user_id, run_id=ids["run_id"]
        )
        assert state is not None
        assert state["verdict"] != "passed"
        assert state["status"] in ("succeeded", "failed", "inconclusive", "error", "cancelled")

        events = await EventService(engines[ROLE_API]).query_durable(
            workspace_id=workspace_id,
            principal_id=user_id,
            run_id=ids["run_id"],
            limit=500,
        )
        assert events
    finally:
        harness.aclose()
