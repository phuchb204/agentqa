from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import scoped_transaction, seed_run
from tests.support.security import create_user, login

pytestmark = pytest.mark.asyncio


async def _two_workspaces(runtime):
    owner_a_id, owner_a_name = await create_user(runtime, "owner-a", "pw-123456")
    owner_b_id, _owner_b_name = await create_user(runtime, "owner-b", "pw-123456")
    workspace_a = await runtime.authorization.create_workspace(
        actor_id=owner_a_id, slug=f"ws-a-{uuid4().hex[:6]}", name="A"
    )
    workspace_b = await runtime.authorization.create_workspace(
        actor_id=owner_b_id, slug=f"ws-b-{uuid4().hex[:6]}", name="B"
    )
    return owner_a_id, owner_a_name, workspace_a.id, owner_b_id, workspace_b.id


async def test_objects_of_other_workspace_are_not_visible(api_client, runtime, role_engines) -> None:
    from datetime import date

    _owner_a_id, owner_a_name, workspace_a, owner_b_id, workspace_b = await _two_workspaces(runtime)
    run_b = await seed_run(role_engines, principal_id=owner_b_id, workspace_id=workspace_b)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=owner_b_id, workspace_id=workspace_b) as session:
        artifact_id = uuid4()
        await session.execute(
            sa.insert(tables.artifacts).values(
                id=artifact_id,
                workspace_id=workspace_b,
                run_id=run_b,
                kind="screenshot",
                state="available",
                media_type="image/png",
                digest="a" * 64,
            )
        )
        await session.execute(
            sa.insert(tables.run_events).values(
                workspace_id=workspace_b,
                run_id=run_b,
                run_seq=1,
                type="run.state_changed",
                actor="owner-b",
                summary={"status": "queued"},
                payload_month=date(2026, 10, 1),
            )
        )

    await login(api_client, owner_a_name, "pw-123456")

    same_workspace_lookup = await api_client.get(f"/api/v1/workspaces/{workspace_a}/runs/{run_b}")
    assert same_workspace_lookup.status_code == 404
    cross_scope_lookup = await api_client.get(f"/api/v1/workspaces/{workspace_b}/runs/{run_b}")
    assert cross_scope_lookup.status_code == 404
    cross_artifact = await api_client.get(f"/api/v1/workspaces/{workspace_a}/artifacts/{artifact_id}")
    assert cross_artifact.status_code == 404
    cross_artifact_scope = await api_client.get(f"/api/v1/workspaces/{workspace_b}/artifacts/{artifact_id}")
    assert cross_artifact_scope.status_code == 404
    events = await api_client.get(f"/api/v1/workspaces/{workspace_a}/runs/{run_b}/events")
    assert events.status_code == 200
    assert events.json()["events"] == []


async def test_artifact_content_requires_membership(api_client, runtime, role_engines) -> None:
    _owner_a_id, owner_a_name, _workspace_a, owner_b_id, workspace_b = await _two_workspaces(runtime)
    async with scoped_transaction(role_engines[ROLE_API], principal_id=owner_b_id, workspace_id=workspace_b) as session:
        artifact_id = uuid4()
        await session.execute(
            sa.insert(tables.artifacts).values(
                id=artifact_id,
                workspace_id=workspace_b,
                kind="dom",
                state="available",
                media_type="text/html",
                digest="b" * 64,
            )
        )
    await login(api_client, owner_a_name, "pw-123456")
    response = await api_client.get(f"/api/v1/workspaces/{workspace_b}/artifacts/{artifact_id}/content")
    assert response.status_code == 404
