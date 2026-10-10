from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["schedules"])


class ScheduleCreateRequest(StrictModel):
    logical_key: str


class ScheduleRevisionRequest(StrictModel):
    content: dict


class ScheduleRevisionSummary(StrictModel):
    revision_id: UUID
    revision_no: int
    content: dict


class ScheduleResponse(StrictModel):
    schedule_id: UUID
    logical_key: str
    enabled: bool
    latest_revision: ScheduleRevisionSummary | None = None


class ScheduleListResponse(StrictModel):
    items: list[ScheduleResponse]


class OccurrenceResponse(StrictModel):
    occurrence_id: UUID
    schedule_id: UUID
    schedule_revision_id: UUID
    occurrence_key: str
    local_wall_time: datetime
    scheduled_at: datetime | None = None
    fold: int
    state: str
    reason: str | None = None
    run_id: UUID | None = None


class OccurrenceListResponse(StrictModel):
    items: list[OccurrenceResponse]


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/schedules", response_model=ScheduleResponse)
async def create_schedule(request: Request, workspace_id: UUID, body: ScheduleCreateRequest) -> ScheduleResponse:
    principal = await _require(request, workspace_id, Permission.SETTINGS_MANAGE)
    runtime = get_runtime(request)
    try:
        schedule_id = await runtime.scheduler.create_schedule(
            workspace_id=workspace_id, principal_id=principal.user_id, logical_key=body.logical_key
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ScheduleResponse(schedule_id=schedule_id, logical_key=body.logical_key, enabled=True)


@router.get("/workspaces/{workspace_id}/schedules", response_model=ScheduleListResponse)
async def list_schedules(request: Request, workspace_id: UUID) -> ScheduleListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    items = await runtime.scheduler.list_schedules(workspace_id=workspace_id, principal_id=principal.user_id)
    return ScheduleListResponse.model_validate({"items": items})


@router.post("/workspaces/{workspace_id}/schedules/{schedule_id}/revisions", response_model=ScheduleRevisionSummary)
async def add_revision(
    request: Request, workspace_id: UUID, schedule_id: UUID, body: ScheduleRevisionRequest
) -> ScheduleRevisionSummary:
    principal = await _require(request, workspace_id, Permission.SETTINGS_MANAGE)
    runtime = get_runtime(request)
    try:
        revision_id, revision_no = await runtime.scheduler.add_revision(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            schedule_id=schedule_id,
            content=body.content,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ScheduleRevisionSummary(revision_id=revision_id, revision_no=revision_no, content=body.content)


@router.post("/workspaces/{workspace_id}/schedules/{schedule_id}/enable", response_model=ScheduleResponse)
async def enable_schedule(request: Request, workspace_id: UUID, schedule_id: UUID) -> ScheduleResponse:
    return await _set_enabled(request, workspace_id, schedule_id, True)


@router.post("/workspaces/{workspace_id}/schedules/{schedule_id}/disable", response_model=ScheduleResponse)
async def disable_schedule(request: Request, workspace_id: UUID, schedule_id: UUID) -> ScheduleResponse:
    return await _set_enabled(request, workspace_id, schedule_id, False)


async def _set_enabled(request: Request, workspace_id: UUID, schedule_id: UUID, enabled: bool) -> ScheduleResponse:
    principal = await _require(request, workspace_id, Permission.SETTINGS_MANAGE)
    runtime = get_runtime(request)
    try:
        await runtime.scheduler.set_enabled(
            workspace_id=workspace_id, principal_id=principal.user_id, schedule_id=schedule_id, enabled=enabled
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    items = await runtime.scheduler.list_schedules(workspace_id=workspace_id, principal_id=principal.user_id)
    current = next((item for item in items if item["schedule_id"] == schedule_id), None)
    if current is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy schedule")
    return ScheduleResponse.model_validate(current)


@router.get("/workspaces/{workspace_id}/schedules/{schedule_id}/occurrences", response_model=OccurrenceListResponse)
async def list_occurrences(request: Request, workspace_id: UUID, schedule_id: UUID) -> OccurrenceListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    occurrences = await runtime.scheduler.list_occurrences(
        workspace_id=workspace_id, principal_id=principal.user_id, schedule_id=schedule_id
    )
    return OccurrenceListResponse.model_validate({"items": [occurrence.__dict__ for occurrence in occurrences]})
