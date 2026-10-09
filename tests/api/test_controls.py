from __future__ import annotations

from uuid import UUID

import pytest

from tests.support.platform import service_case_revision

pytestmark = pytest.mark.asyncio


async def submit(api_client, owner, runtime, *, key: str) -> tuple[str, str]:
    workspace_id, csrf, user_id = owner
    promotion = await service_case_revision(
        runtime,
        workspace_id=UUID(workspace_id),
        principal_id=UUID(user_id),
        actor="tester",
        logical_key=f"controls_{key}",
    )
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs",
        json={"case_revision_ids": [str(promotion.revision_id)], "provided_capabilities": []},
        headers={"x-csrf-token": csrf, "idempotency-key": key},
    )
    assert response.status_code == 202
    return workspace_id, response.json()["run_id"]


async def test_request_controls_and_list_requested_state(api_client, owner, runtime) -> None:
    workspace_id, run_id = await submit(api_client, owner, runtime, key="controls-1")
    _ws, csrf, _user = owner
    headers = {"x-csrf-token": csrf}
    first = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls",
        json={"action": "cancel", "reason": "test"},
        headers=headers,
    )
    assert first.status_code == 202
    control_id = first.json()["control_id"]
    assert first.json()["control_revision"] == 1

    second = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls",
        json={"action": "pause"},
        headers=headers,
    )
    assert second.status_code == 202
    assert second.json()["control_revision"] == 2

    listing = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls")
    assert listing.status_code == 200
    controls = listing.json()["controls"]
    assert len(controls) == 2
    assert controls[0]["control_id"] == control_id
    assert controls[0]["effective_at"] is None

    state = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}")
    assert len(state.json()["controls"]) == 2

    invalid = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls",
        json={"action": "khong-ton-tai"},
        headers=headers,
    )
    assert invalid.status_code == 422
