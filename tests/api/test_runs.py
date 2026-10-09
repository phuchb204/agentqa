from __future__ import annotations

from uuid import UUID

import pytest

from tests.support.platform import service_case_revision

pytestmark = pytest.mark.asyncio


async def submit_run(api_client, workspace_id: str, csrf: str, revision_id: UUID, *, key: str, gate: str = "strict"):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs",
        json={
            "case_revision_ids": [str(revision_id)],
            "gate_profile": gate,
            "provided_capabilities": [],
        },
        headers={"x-csrf-token": csrf, "idempotency-key": key},
    )


async def test_submit_returns_202_and_state_before_worker(api_client, owner, runtime) -> None:
    workspace_id, csrf, user_id = owner
    promotion = await service_case_revision(
        runtime,
        workspace_id=UUID(workspace_id),
        principal_id=UUID(user_id),
        actor="tester",
        logical_key="api_submit",
    )
    response = await submit_run(api_client, workspace_id, csrf, promotion.revision_id, key="submit-1")
    assert response.status_code == 202
    data = response.json()
    assert data["planned_executions"] == 1
    assert data["status"] == "queued"
    assert data["blocked"] is False
    run_id = data["run_id"]

    state = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}")
    assert state.status_code == 200
    state_data = state.json()
    assert state_data["status"] == "queued"
    assert state_data["executions"][0]["status"] == "queued"
    assert state_data["last_run_seq"] >= 1

    result = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/result")
    assert result.status_code == 409


async def test_submit_idempotency_same_key(api_client, owner, runtime) -> None:
    workspace_id, csrf, user_id = owner
    promotion = await service_case_revision(
        runtime,
        workspace_id=UUID(workspace_id),
        principal_id=UUID(user_id),
        actor="tester",
        logical_key="api_idem",
    )
    first = await submit_run(api_client, workspace_id, csrf, promotion.revision_id, key="same-key")
    second = await submit_run(api_client, workspace_id, csrf, promotion.revision_id, key="same-key")
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]

    conflict = await submit_run(
        api_client, workspace_id, csrf, promotion.revision_id, key="same-key", gate="allow_healing"
    )
    assert conflict.status_code == 409
