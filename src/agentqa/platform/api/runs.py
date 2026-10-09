from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.observation import Modality
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.runs.service import SubmitRequest
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(prefix="/api/v1", tags=["runs"])


class SubmitRunRequest(StrictModel):
    case_revision_ids: list[UUID]
    environment_revision_id: UUID | None = None
    policy: str = "default"
    gate_profile: str = "default"
    budgets: dict[str, int] = {}
    provided_capabilities: list[str] = []
    idempotency_key: str | None = None


class SubmitRunResponse(StrictModel):
    run_id: UUID
    snapshot_digest: str
    planned_executions: int
    blocked: bool
    blocked_reasons: list[str]
    status: str


class ExecutionStateResponse(StrictModel):
    execution_id: UUID
    logical_key: str
    status: str
    verdict: str | None = None


class ControlStateResponse(StrictModel):
    control_id: UUID
    action: str
    requested_at: datetime
    effective_at: datetime | None = None
    effective_reason: str | None = None


class RunStateResponse(StrictModel):
    run_id: UUID
    status: str
    verdict: str | None = None
    gate: str | None = None
    reasons: list[str] = []
    snapshot_digest: str | None = None
    last_run_seq: int = 0
    executions: list[ExecutionStateResponse] = []
    controls: list[ControlStateResponse] = []


class RunResultResponse(StrictModel):
    run_id: UUID
    status: str
    verdict: str | None = None
    gate: str | None = None
    reasons: list[str] = []
    terminal: bool
    executions: list[ExecutionStateResponse] = []


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/runs", status_code=202, response_model=SubmitRunResponse)
async def submit_run(request: Request, workspace_id: UUID, body: SubmitRunRequest) -> SubmitRunResponse:
    principal = await _require(request, workspace_id, Permission.RUN_SUBMIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    idempotency_key = request.headers.get("idempotency-key") or body.idempotency_key or uuid4().hex
    try:
        outcome = await runtime.runs.submit(
            SubmitRequest(
                workspace_id=workspace_id,
                principal_id=principal.user_id,
                actor=principal.username,
                idempotency_key=idempotency_key,
                case_revision_ids=tuple(body.case_revision_ids),
                environment_revision_id=body.environment_revision_id,
                policy=body.policy,
                observation_mode=Modality.SEMANTIC,
                budgets=dict(body.budgets),
                gate_profile=body.gate_profile,
                provided_capabilities=frozenset(body.provided_capabilities),
            )
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return SubmitRunResponse(
        run_id=outcome.run_id,
        snapshot_digest=outcome.snapshot_digest,
        planned_executions=outcome.planned_executions,
        blocked=outcome.blocked,
        blocked_reasons=list(outcome.blocked_reasons),
        status=outcome.status,
    )


def _read_model(request: Request) -> RunReadModel:
    runtime = get_runtime(request)
    return RunReadModel(runtime.engines[ROLE_API])


@router.get("/workspaces/{workspace_id}/runs/{run_id}", response_model=RunStateResponse)
async def get_run_state(request: Request, workspace_id: UUID, run_id: UUID) -> RunStateResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    state = await _read_model(request).run_state(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if state is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return RunStateResponse.model_validate(state)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/result", response_model=RunResultResponse)
async def get_run_result(request: Request, workspace_id: UUID, run_id: UUID) -> RunResultResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    result = await _read_model(request).run_result(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if result is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    if not result["terminal"]:
        raise ApiError(409, ErrorCode.INPUT_INVALID, "Run chưa terminal")
    return RunResultResponse.model_validate(result)
