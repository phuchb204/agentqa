from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.runs import ControlAction
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(prefix="/api/v1", tags=["controls"])


class ControlRequestBody(StrictModel):
    action: ControlAction
    reason: str | None = None


class ControlResponse(StrictModel):
    control_id: UUID
    control_revision: int


class ControlListEntry(StrictModel):
    control_id: UUID
    action: str
    requested_at: datetime
    effective_at: datetime | None = None
    effective_reason: str | None = None


class ControlListResponse(StrictModel):
    controls: list[ControlListEntry] = []


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/runs/{run_id}/controls", status_code=202, response_model=ControlResponse)
async def request_control(
    request: Request, workspace_id: UUID, run_id: UUID, body: ControlRequestBody
) -> ControlResponse:
    principal = await _require(request, workspace_id, Permission.RUN_CONTROL)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        receipt = await runtime.runs.request_control(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            run_id=run_id,
            action=body.action,
            reason=body.reason,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ControlResponse(control_id=receipt.control_id, control_revision=receipt.control_revision)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/controls", response_model=ControlListResponse)
async def list_controls(request: Request, workspace_id: UUID, run_id: UUID) -> ControlListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    state = await RunReadModel(runtime.engines[ROLE_API]).run_state(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if state is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return ControlListResponse(controls=[ControlListEntry.model_validate(item) for item in state["controls"]])
