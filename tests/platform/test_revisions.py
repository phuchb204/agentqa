from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import yaml
from tests.support.security import csrf_headers

pytestmark = pytest.mark.asyncio

CASES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"
CASE_FIXTURE = CASES_DIR / "valid_case_minimal.yaml"


def case_content(logical_key: str = "start_flow") -> dict:
    document = yaml.safe_load(CASE_FIXTURE.read_text(encoding="utf-8"))
    document["logical_key"] = logical_key
    return document


async def _create_case(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_draft_if_match_flow_and_promotion(api_client, owner) -> None:
    workspace_id, csrf = owner
    case_id = await _create_case(api_client, csrf, workspace_id, "login_flow")
    content = case_content("login_flow")

    missing = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": content},
        headers=csrf_headers(csrf),
    )
    assert missing.status_code == 428

    created = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": content},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert created.status_code == 200, created.text
    assert created.json()["edit_version"] == 1

    fetched = await api_client.get(f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft")
    assert fetched.status_code == 200
    assert fetched.headers["etag"] == '"1"'
    assert fetched.json()["content"]["logical_key"] == "login_flow"

    stale = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": content},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert stale.status_code == 412

    updated_content = case_content("login_flow")
    updated_content["title"] = "Đăng nhập"
    updated = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": updated_content},
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert updated.status_code == 200
    assert updated.json()["edit_version"] == 2

    validation = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/validate",
        json={"content": updated_content},
        headers=csrf_headers(csrf),
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is True

    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"2"'},
    )
    assert promoted.status_code == 200, promoted.text
    receipt = promoted.json()
    assert receipt["revision_no"] == 1
    assert len(receipt["content_digest"]) == 64

    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions")
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1
    assert revisions.json()[0]["content_digest"] == receipt["content_digest"]
    assert revisions.json()[0]["lifecycle"] == "ready"

    again = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"2"'},
    )
    assert again.status_code == 200
    assert again.json()["revision_no"] == 2
    assert again.json()["supersedes"] == receipt["revision_id"]


async def test_invalid_draft_cannot_promote(api_client, owner) -> None:
    workspace_id, csrf = owner
    case_id = await _create_case(api_client, csrf, workspace_id, "broken_case")
    created = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": {"schema_version": "case/1"}},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert created.status_code == 200
    validation = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/validate",
        headers=csrf_headers(csrf),
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert validation.json()["field_errors"]

    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert promoted.status_code == 422
    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions")
    assert revisions.json() == []


async def test_ready_revision_immutable_and_archive_keeps_digest(api_client, owner, role_engines, runtime) -> None:
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError
    from tests.support.postgres import scoped_transaction

    from agentqa.platform.storage import tables

    workspace_id, csrf = owner
    case_id = await _create_case(api_client, csrf, workspace_id, "immutable_case")
    await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": case_content("immutable_case")},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    revision_id = promoted.json()["revision_id"]
    digest = promoted.json()["content_digest"]

    principal = await runtime.users.create(username=f"immut-{UUID(workspace_id).hex[:8]}", password="pw-123456")
    async with scoped_transaction(
        role_engines["agentqa_migrate"], principal_id=principal.id, workspace_id=UUID(workspace_id)
    ) as session:
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                sa.update(tables.case_revisions)
                .where(tables.case_revisions.c.id == UUID(revision_id))
                .values(content={"tampered": True})
            )
        assert "agentqa_revision_immutable" in str(error.value)

    archived = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions/{revision_id}/archive",
        headers=csrf_headers(csrf),
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["lifecycle"] == "archived"
    assert archived.json()["content_digest"] == digest
    assert archived.json()["content"]["logical_key"] == "immutable_case"


async def test_environment_and_suite_revisions(api_client, owner) -> None:
    workspace_id, csrf = owner
    application = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/applications",
        json={"slug": "shopflow", "name": "Shopflow"},
        headers=csrf_headers(csrf),
    )
    assert application.status_code == 200, application.text
    application_id = application.json()["id"]
    environment_content = {
        "schema_version": "environment/1",
        "base_url": "https://app.example.com",
        "network_profile": "local-allowlist",
        "fixture_refs": ["fixture/shopflow"],
    }
    environment = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/applications/{application_id}/environment-revisions",
        json={"content": environment_content},
        headers=csrf_headers(csrf),
    )
    assert environment.status_code == 200, environment.text
    assert environment.json()["revision_no"] == 1

    suite = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites",
        json={"logical_key": "smoke"},
        headers=csrf_headers(csrf),
    )
    assert suite.status_code == 200, suite.text
    suite_id = suite.json()["id"]
    suite_content = {
        "schema_version": "suite/1",
        "logical_key": "smoke",
        "case_refs": [{"logical_key": "start_flow", "revision_no": 1}],
    }
    suite_revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={"content": suite_content},
        headers=csrf_headers(csrf),
    )
    assert suite_revision.status_code == 200, suite_revision.text
    assert suite_revision.json()["content_digest"]

    invalid = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={"content": {"schema_version": "suite/1", "logical_key": "smoke"}},
        headers=csrf_headers(csrf),
    )
    assert invalid.status_code == 422

    listed = await api_client.get(f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_export_import_portable_and_rejects_foreign_rights(api_client, owner, runtime) -> None:
    from tests.support.security import create_user

    from agentqa.contracts.errors import ErrorCode
    from agentqa.platform.identity.models import IdentityError

    workspace_id, csrf = owner
    case_id = await _create_case(api_client, csrf, workspace_id, "portable_case")
    await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": case_content("portable_case")},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    exported = await api_client.get(f"/api/v1/workspaces/{workspace_id}/revisions/export?kind=case")
    assert exported.status_code == 200, exported.text
    bundle = exported.json()
    serialized = str(bundle)
    assert "workspace_id" not in serialized
    assert "credential" not in serialized
    assert bundle["revisions"][0]["content_digest"]

    user_id, username = await create_user(runtime, "importer", "pw-123456")
    target = await runtime.authorization.create_workspace(actor_id=user_id, slug="import-target", name="Import target")
    receipts = await runtime.revisions.import_bundle(
        workspace_id=target.id, principal_id=user_id, actor=username, bundle=bundle
    )
    assert len(receipts) == 1

    poisoned = {
        "schema_version": bundle["schema_version"],
        "kind": bundle["kind"],
        "revisions": [dict(bundle["revisions"][0], confirmation_ref="owner-approval")],
    }
    with pytest.raises(IdentityError) as error:
        await runtime.revisions.import_bundle(
            workspace_id=target.id, principal_id=user_id, actor=username, bundle=poisoned
        )
    assert error.value.code is ErrorCode.PERMISSION_DENIED
