from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import (
    ROLE_PERMISSIONS,
    IdentityError,
    Permission,
    Role,
)
from tests.support.security import create_user, create_workspace, csrf_headers, error_body, login

pytestmark = pytest.mark.asyncio


async def test_role_permission_matrix() -> None:
    assert Permission.RUN_SUBMIT not in ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.CASE_EDIT not in ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.RUN_SUBMIT in ROLE_PERMISSIONS[Role.RUNNER]
    assert Permission.CASE_EDIT not in ROLE_PERMISSIONS[Role.RUNNER]
    assert Permission.CASE_EDIT in ROLE_PERMISSIONS[Role.EDITOR]
    assert Permission.MEMBERSHIP_MANAGE not in ROLE_PERMISSIONS[Role.EDITOR]
    assert Permission.MEMBERSHIP_MANAGE in ROLE_PERMISSIONS[Role.OWNER]
    assert Permission.SETTINGS_MANAGE in ROLE_PERMISSIONS[Role.OWNER]


async def test_service_role_enforcement_and_cache_invalidation(runtime) -> None:
    owner_id, _owner_name = await create_user(runtime, "owner", "pw-123456")
    editor_id, _editor_name = await create_user(runtime, "editor", "pw-123456")
    workspace = await runtime.authorization.create_workspace(
        actor_id=owner_id, slug=f"ws-{uuid4().hex[:8]}", name="Workspace"
    )
    await runtime.authorization.add_membership(
        workspace_id=workspace.id, actor_id=owner_id, user_id=editor_id, role=Role.EDITOR
    )
    await runtime.authorization.require(workspace_id=workspace.id, user_id=editor_id, permission=Permission.RUN_SUBMIT)
    with pytest.raises(IdentityError) as error:
        await runtime.authorization.require(
            workspace_id=workspace.id, user_id=editor_id, permission=Permission.MEMBERSHIP_MANAGE
        )
    assert error.value.code is ErrorCode.PERMISSION_DENIED

    cached = runtime.authorization.cache.get(workspace.id, editor_id)
    assert cached is not None
    await runtime.authorization.change_role(
        workspace_id=workspace.id, actor_id=owner_id, user_id=editor_id, role=Role.VIEWER
    )
    assert runtime.authorization.cache.get(workspace.id, editor_id) is None
    with pytest.raises(IdentityError):
        await runtime.authorization.require(
            workspace_id=workspace.id, user_id=editor_id, permission=Permission.RUN_SUBMIT
        )


async def test_owner_last_service_invariant(runtime) -> None:
    owner_id, _name = await create_user(runtime, "owner", "pw-123456")
    other_id, _name2 = await create_user(runtime, "other", "pw-123456")
    workspace = await runtime.authorization.create_workspace(
        actor_id=owner_id, slug=f"ws-{uuid4().hex[:8]}", name="Workspace"
    )
    with pytest.raises(IdentityError) as error:
        await runtime.authorization.remove_membership(workspace_id=workspace.id, actor_id=owner_id, user_id=owner_id)
    assert error.value.code is ErrorCode.INPUT_INVALID

    await runtime.authorization.add_membership(
        workspace_id=workspace.id, actor_id=owner_id, user_id=other_id, role=Role.OWNER
    )
    await runtime.authorization.remove_membership(workspace_id=workspace.id, actor_id=other_id, user_id=owner_id)
    with pytest.raises(IdentityError):
        await runtime.authorization.change_role(
            workspace_id=workspace.id, actor_id=other_id, user_id=other_id, role=Role.EDITOR
        )


async def test_api_requires_authentication(api_client) -> None:
    response = await api_client.get("/api/v1/workspaces")
    assert response.status_code == 401
    body = error_body(response)
    assert body.code is ErrorCode.PERMISSION_DENIED


async def test_api_authorization_and_scope(api_client, runtime) -> None:
    _owner_id, owner_name = await create_user(runtime, "owner", "pw-123456")
    viewer_id, viewer_name = await create_user(runtime, "viewer", "pw-123456")
    owner_csrf = await login(api_client, owner_name, "pw-123456")
    workspace_id = await create_workspace(api_client, owner_csrf, f"ws-{uuid4().hex[:8]}")
    second_workspace = await create_workspace(api_client, owner_csrf, f"ws-{uuid4().hex[:8]}")

    response = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Renamed"},
        headers=csrf_headers(owner_csrf),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"

    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/memberships",
        json={"username": viewer_name, "role": "viewer"},
        headers=csrf_headers(owner_csrf),
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == str(viewer_id)

    await api_client.post("/api/v1/auth/logout", headers=csrf_headers(owner_csrf))
    viewer_csrf = await login(api_client, viewer_name, "pw-123456")

    response = await api_client.get("/api/v1/workspaces")
    assert response.status_code == 200
    listed = {item["id"] for item in response.json()}
    assert workspace_id in listed
    assert second_workspace not in listed

    response = await api_client.get(f"/api/v1/workspaces/{second_workspace}")
    assert response.status_code == 404
    assert error_body(response).code is ErrorCode.NOT_FOUND

    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/memberships",
        json={"username": viewer_name, "role": "editor"},
        headers=csrf_headers(viewer_csrf),
    )
    assert response.status_code == 403
    assert error_body(response).code is ErrorCode.PERMISSION_DENIED


async def test_api_error_body_has_no_internals(api_client) -> None:
    response = await api_client.get("/api/v1/workspaces")
    assert response.status_code == 401
    text = response.text
    assert "Traceback" not in text
    assert "agentqa.platform" not in text
    payload = response.json()
    assert set(payload) <= {"code", "message", "field_errors", "request_id", "retryable"}
    assert error_body(response).message


async def test_permission_flags_recorded(api_client, runtime) -> None:
    _owner_id, owner_name = await create_user(runtime, "owner", "pw-123456")
    member_id, member_name = await create_user(runtime, "member", "pw-123456")
    owner_csrf = await login(api_client, owner_name, "pw-123456")
    workspace_id = await create_workspace(api_client, owner_csrf, f"ws-{uuid4().hex[:8]}")
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/memberships",
        json={"username": member_name, "role": "viewer", "permission_flags": ["artifact_export"]},
        headers=csrf_headers(owner_csrf),
    )
    assert response.status_code == 200, response.text
    membership = await runtime.authorization.membership(workspace_id=UUID(workspace_id), user_id=member_id)
    assert membership is not None
    assert "artifact_export" in membership.permission_flags
