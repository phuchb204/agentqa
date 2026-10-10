from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["exploration"])


class ExplorationJobRequest(StrictModel):
    environment_revision_id: UUID
    goal: str
    max_pages: int = 20
    max_depth: int = 2


class ExplorationResponse(StrictModel):
    job_id: UUID
    state: str
    error_reason: str | None = None
    environment_revision_id: UUID | None = None
    write_allowed: bool
    pages: list[dict]
    actions: list[dict]
    coverage_gaps: list[dict]
    proposals: list[dict]


def _response(outcome) -> ExplorationResponse:
    return ExplorationResponse(
        job_id=outcome.job_id,
        state=outcome.state,
        error_reason=outcome.error_reason,
        environment_revision_id=outcome.environment_revision_id,
        write_allowed=outcome.write_allowed,
        pages=outcome.pages,
        actions=outcome.actions,
        coverage_gaps=outcome.coverage_gaps,
        proposals=outcome.proposals,
    )


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/exploration-jobs", response_model=ExplorationResponse)
async def create_exploration_job(
    request: Request, workspace_id: UUID, payload: ExplorationJobRequest
) -> ExplorationResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        outcome = await runtime.exploration.create_job(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            environment_revision_id=payload.environment_revision_id,
            goal=payload.goal,
            max_pages=payload.max_pages,
            max_depth=payload.max_depth,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _response(outcome)


@router.get("/workspaces/{workspace_id}/exploration-jobs/{job_id}", response_model=ExplorationResponse)
async def get_exploration_job(request: Request, workspace_id: UUID, job_id: UUID) -> ExplorationResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        outcome = await runtime.exploration.get_job(
            workspace_id=workspace_id, principal_id=principal.user_id, job_id=job_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _response(outcome)
