from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import (
    authenticate,
    enforce_browser_guard,
    get_runtime,
    to_api_error,
)
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission, Role

router = APIRouter(prefix="/api/v1", tags=["workspaces"])


class WorkspaceCreateRequest(StrictModel):
    slug: str
    name: str


class WorkspacePatchRequest(StrictModel):
    name: str


class WorkspaceResponse(StrictModel):
    id: UUID
    slug: str
    name: str


class MembershipCreateRequest(StrictModel):
    user_id: UUID | None = None
    username: str | None = None
    role: Role
    permission_flags: list[str] = []


class MembershipPatchRequest(StrictModel):
    role: Role


class MembershipResponse(StrictModel):
    workspace_id: UUID
    user_id: UUID
    role: Role
    permission_flags: list[str] = []


def _to_membership_response(record) -> MembershipResponse:
    return MembershipResponse(
        workspace_id=record.workspace_id,
        user_id=record.user_id,
        role=record.role,
        permission_flags=list(record.permission_flags),
    )


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        return principal, await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=permission
        )
    except IdentityError as error:
        raise to_api_error(error) from error


@router.post("/workspaces", response_model=WorkspaceResponse)
async def create_workspace(request: Request, payload: WorkspaceCreateRequest) -> WorkspaceResponse:
    principal = await authenticate(request)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        workspace = await runtime.authorization.create_workspace(
            actor_id=principal.user_id, slug=payload.slug, name=payload.name
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return WorkspaceResponse(id=workspace.id, slug=workspace.slug, name=workspace.name)


@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(request: Request) -> list[WorkspaceResponse]:
    principal = await authenticate(request)
    runtime = get_runtime(request)
    workspaces = await runtime.authorization.list_workspaces(user_id=principal.user_id)
    return [WorkspaceResponse(id=item.id, slug=item.slug, name=item.name) for item in workspaces]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(request: Request, workspace_id: UUID) -> WorkspaceResponse:
    principal, _membership = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    workspaces = await runtime.authorization.list_workspaces(user_id=principal.user_id)
    for item in workspaces:
        if item.id == workspace_id:
            return WorkspaceResponse(id=item.id, slug=item.slug, name=item.name)
    raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy workspace trong scope")


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def patch_workspace(request: Request, workspace_id: UUID, payload: WorkspacePatchRequest) -> WorkspaceResponse:
    principal, _membership = await _require(request, workspace_id, Permission.WORKSPACE_MANAGE)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        updated = await runtime.authorization.rename_workspace(
            workspace_id=workspace_id, user_id=principal.user_id, name=payload.name
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return WorkspaceResponse(id=updated.id, slug=updated.slug, name=updated.name)


@router.get("/workspaces/{workspace_id}/memberships", response_model=list[MembershipResponse])
async def list_memberships(request: Request, workspace_id: UUID) -> list[MembershipResponse]:
    principal, _membership = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    records = await runtime.authorization.list_memberships(workspace_id=workspace_id, user_id=principal.user_id)
    return [_to_membership_response(record) for record in records]


@router.post("/workspaces/{workspace_id}/memberships", response_model=MembershipResponse)
async def add_membership(request: Request, workspace_id: UUID, payload: MembershipCreateRequest) -> MembershipResponse:
    principal, _membership = await _require(request, workspace_id, Permission.MEMBERSHIP_MANAGE)
    enforce_browser_guard(request, principal)
    if (payload.user_id is None) == (payload.username is None):
        raise ApiError(422, ErrorCode.INPUT_INVALID, "Cần đúng một trong user_id hoặc username")
    runtime = get_runtime(request)
    target_user_id = payload.user_id
    if target_user_id is None:
        user = await runtime.users.find_by_username(payload.username or "")
        if user is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy user")
        target_user_id = user.id
    try:
        record = await runtime.authorization.add_membership(
            workspace_id=workspace_id,
            actor_id=principal.user_id,
            user_id=target_user_id,
            role=payload.role,
            permission_flags=tuple(payload.permission_flags),
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_membership_response(record)


@router.patch("/workspaces/{workspace_id}/memberships/{user_id}", response_model=MembershipResponse)
async def patch_membership(
    request: Request, workspace_id: UUID, user_id: UUID, payload: MembershipPatchRequest
) -> MembershipResponse:
    principal, _membership = await _require(request, workspace_id, Permission.MEMBERSHIP_MANAGE)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        record = await runtime.authorization.change_role(
            workspace_id=workspace_id, actor_id=principal.user_id, user_id=user_id, role=payload.role
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_membership_response(record)


@router.delete("/workspaces/{workspace_id}/memberships/{user_id}", status_code=204)
async def delete_membership(request: Request, workspace_id: UUID, user_id: UUID) -> None:
    principal, _membership = await _require(request, workspace_id, Permission.MEMBERSHIP_MANAGE)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.remove_membership(
            workspace_id=workspace_id, actor_id=principal.user_id, user_id=user_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
