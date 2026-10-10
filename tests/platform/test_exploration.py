from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from tests.support.exploration import FakeSitePort
from tests.support.postgres import scoped_transaction
from tests.support.security import csrf_headers

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio

BASE = "http://site.test/"


async def _promote_environment(api_client, csrf: str, workspace_id: str, *, allow_write: bool) -> str:
    application = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/applications",
        json={"slug": f"site-{uuid4().hex[:6]}", "name": "Site"},
        headers=csrf_headers(csrf),
    )
    assert application.status_code == 200, application.text
    content = {
        "schema_version": "environment/1",
        "base_url": BASE,
        "network_profile": "local-allowlist",
        "allowed_origins": ["http://site.test"],
        "allow_write_actions": allow_write,
    }
    revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/applications/{application.json()['id']}/environment-revisions",
        json={"content": content},
        headers=csrf_headers(csrf),
    )
    assert revision.status_code == 200, revision.text
    return revision.json()["revision_id"]


async def _explore(api_client, csrf: str, workspace_id: str, environment_revision_id: str, **overrides):
    payload = {"environment_revision_id": environment_revision_id, "goal": "Khám phá luồng chính", **overrides}
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/exploration-jobs",
        json=payload,
        headers=csrf_headers(csrf),
    )


async def test_exploration_default_read_only_records_coverage_gaps(
    api_client, runtime, owner, exploration_port: FakeSitePort
) -> None:
    workspace_id, csrf = owner
    environment_revision_id = await _promote_environment(api_client, csrf, workspace_id, allow_write=False)

    response = await _explore(api_client, csrf, workspace_id, environment_revision_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "succeeded"
    assert body["write_allowed"] is False
    assert [page["url"] for page in body["pages"]] == [BASE, f"{BASE}a", f"{BASE}b"]
    assert len(body["actions"]) == 1
    action = body["actions"][0]
    assert action["attempted"] is False
    assert action["allowed"] is False
    assert action["reason"] == "write_actions_disabled"
    assert exploration_port.writes == []
    gaps = {(gap["kind"], gap["url"]) for gap in body["coverage_gaps"]}
    assert ("external_origin", "http://evil.example/x") in gaps
    assert body["proposals"] and body["proposals"][0]["note"] == "exploration_proposal"
    assert "coverage" not in body or "full" not in str(body.get("coverage", ""))

    fetched = await api_client.get(f"/api/v1/workspaces/{workspace_id}/exploration-jobs/{body['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["pages"] == body["pages"]

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        row = (
            await session.execute(
                sa.select(tables.exploration_results).where(tables.exploration_results.c.job_id == UUID(body["job_id"]))
            )
        ).one()
        job = (
            await session.execute(
                sa.select(tables.authoring_jobs).where(tables.authoring_jobs.c.id == UUID(body["job_id"]))
            )
        ).one()
    assert row.write_allowed is False
    assert job.kind == "exploration"
    assert job.state == "succeeded"


async def test_exploration_write_allowed_only_when_environment_pins_it(
    api_client, owner, exploration_port: FakeSitePort
) -> None:
    workspace_id, csrf = owner
    environment_revision_id = await _promote_environment(api_client, csrf, workspace_id, allow_write=True)
    response = await _explore(api_client, csrf, workspace_id, environment_revision_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["write_allowed"] is True
    action = body["actions"][0]
    assert action["attempted"] is True
    assert action["allowed"] is True
    assert action["reason"] is None
    assert exploration_port.writes == [BASE]


async def test_exploration_depth_limit_is_a_gap(api_client, owner) -> None:
    workspace_id, csrf = owner
    environment_revision_id = await _promote_environment(api_client, csrf, workspace_id, allow_write=False)
    response = await _explore(api_client, csrf, workspace_id, environment_revision_id, max_depth=0)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [page["url"] for page in body["pages"]] == [BASE]
    reasons = {(gap["kind"], gap["reason"]) for gap in body["coverage_gaps"]}
    assert ("depth_limit", "max_depth_reached") in reasons
    assert ("external_origin", "blocked_external_origin") in reasons


async def test_exploration_requires_ready_environment(api_client, owner) -> None:
    workspace_id, csrf = owner
    missing = await _explore(api_client, csrf, workspace_id, str(uuid4()))
    assert missing.status_code == 404
