from __future__ import annotations

from uuid import UUID

import pytest

from agentqa.platform.api import events as events_api
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope
from tests.support.platform import service_case_revision

pytestmark = pytest.mark.asyncio


async def submit(api_client, owner, runtime, *, key: str) -> tuple[str, str]:
    workspace_id, csrf, user_id = owner
    promotion = await service_case_revision(
        runtime,
        workspace_id=UUID(workspace_id),
        principal_id=UUID(user_id),
        actor="tester",
        logical_key=f"events_{key}",
    )
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/runs",
        json={"case_revision_ids": [str(promotion.revision_id)], "provided_capabilities": []},
        headers={"x-csrf-token": csrf, "idempotency-key": key},
    )
    assert response.status_code == 202
    return workspace_id, response.json()["run_id"]


async def test_events_list_and_cursor_no_duplicate(api_client, owner, runtime) -> None:
    workspace_id, run_id = await submit(api_client, owner, runtime, key="events-list")
    first = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/events?cursor=0")
    assert first.status_code == 200
    payload = first.json()
    assert payload["events"]
    assert payload["events"][0]["run_seq"] == 1
    cursor = payload["cursor"]

    second = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/events?cursor={cursor}")
    assert second.status_code == 200
    assert second.json()["events"] == []
    assert second.json()["cursor"] == cursor


async def test_sse_stream_snapshot_and_terminal_close(api_client, owner, runtime, monkeypatch) -> None:
    monkeypatch.setattr(events_api, "SSE_IDLE_LIMIT", 3)
    monkeypatch.setattr(events_api, "SSE_POLL_SECONDS", 0.01)
    workspace_id, run_id = await submit(api_client, owner, runtime, key="events-stream")

    stream = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/events/stream")
    assert stream.status_code == 200
    text = stream.text
    assert "event: snapshot" in text
    assert "event: timeout" in text
    assert f'"run_id": "{run_id}"' in text

    factory = create_session_factory(runtime.engines["agentqa_api"])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=UUID(owner[2]), workspace_id=UUID(workspace_id))
        await session.execute(
            tables.runs.update()
            .where(tables.runs.c.id == UUID(run_id))
            .values(status="succeeded", verdict="inconclusive")
        )

    resumed = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/events/stream?cursor=1")
    resumed_text = resumed.text
    assert '"cursor": 1' in resumed_text
    assert "event: closed" in resumed_text
    assert resumed_text.count("event: run_event") == 0
