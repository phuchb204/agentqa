from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.experiments.runner import ExperimentService, ExperimentValidationError
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(prefix="/api/v1", tags=["experiments"])


class RevisionCreateRequest(StrictModel):
    logical_key: str
    content: dict[str, Any]


class RevisionResponse(StrictModel):
    revision_id: UUID
    experiment_id: UUID
    logical_key: str
    revision_no: int
    content_digest: str


class RevisionListResponse(StrictModel):
    items: list[RevisionResponse]


class ExecuteResponse(StrictModel):
    revision_id: UUID
    attempt_no: int
    slots: int
    completed: int
    blocked: int
    errors: int


async def _require(request: Request, workspace_id: UUID):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.WORKSPACE_READ
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


class _UnavailableRunner:
    async def run_slot(self, slot, arm_payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "blocked", "blocked_reason": "runner_unavailable"}


@router.post("/workspaces/{workspace_id}/experiments/revisions", status_code=201, response_model=RevisionResponse)
async def create_revision(request: Request, workspace_id: UUID, body: RevisionCreateRequest) -> RevisionResponse:
    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    service = ExperimentService(runtime.engines[ROLE_API])
    try:
        view = await service.create_revision(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            logical_key=body.logical_key,
            content=body.content,
        )
    except ExperimentValidationError as error:
        raise ApiError(
            status_code=422,
            code=ErrorCode.INPUT_INVALID,
            message="Manifest không tương thích",
            field_errors=[],
        ) from error
    return RevisionResponse(
        revision_id=view.revision_id,
        experiment_id=view.experiment_id,
        logical_key=view.logical_key,
        revision_no=view.revision_no,
        content_digest=view.content_digest,
    )


@router.get("/workspaces/{workspace_id}/experiments/revisions", response_model=RevisionListResponse)
async def list_revisions(request: Request, workspace_id: UUID) -> RevisionListResponse:
    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    service = ExperimentService(runtime.engines[ROLE_API])
    views = await service.list_revisions(workspace_id=workspace_id, principal_id=principal.user_id)
    return RevisionListResponse(
        items=[
            RevisionResponse(
                revision_id=view.revision_id,
                experiment_id=view.experiment_id,
                logical_key=view.logical_key,
                revision_no=view.revision_no,
                content_digest=view.content_digest,
            )
            for view in views
        ]
    )


@router.post("/workspaces/{workspace_id}/experiments/revisions/{revision_id}/execute", response_model=ExecuteResponse)
async def execute_revision(request: Request, workspace_id: UUID, revision_id: UUID) -> ExecuteResponse:
    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    service = ExperimentService(runtime.engines[ROLE_API])
    try:
        summary = await service.execute(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            revision_id=revision_id,
            slot_runner=_UnavailableRunner(),
        )
    except KeyError as error:
        raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message=str(error)) from error
    return ExecuteResponse(
        revision_id=revision_id,
        attempt_no=summary["attempt_no"],
        slots=summary["slots"],
        completed=summary["completed"],
        blocked=summary["blocked"],
        errors=summary["errors"],
    )


@router.get("/workspaces/{workspace_id}/experiments/revisions/{revision_id}/results")
async def revision_results(request: Request, workspace_id: UUID, revision_id: UUID) -> dict[str, Any]:
    from agentqa.platform.experiments import ExperimentManifest, compute_analysis

    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    service = ExperimentService(runtime.engines[ROLE_API])
    try:
        results = await service.results(
            workspace_id=workspace_id, principal_id=principal.user_id, revision_id=revision_id
        )
    except KeyError as error:
        raise ApiError(status_code=404, code=ErrorCode.NOT_FOUND, message=str(error)) from error
    manifest = ExperimentManifest.model_validate(results["manifest"])
    results["analysis"] = compute_analysis(manifest, results["slots"])
    return results
