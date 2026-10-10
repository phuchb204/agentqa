from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.service import DraftSubmitRequest

router = APIRouter(prefix="/api/v1", tags=["authoring"])


class SourceInput(StrictModel):
    source_id: UUID
    revision_no: int | None = None


class AuthoringJobRequest(StrictModel):
    goal: str
    url: str | None = None
    expectations: list[str] = []
    requirement_keys: list[str] = []
    sources: list[SourceInput] = []
    model_requested: str | None = None


class ProposalResponse(StrictModel):
    proposal_id: UUID
    job_id: UUID
    title: str
    case_kind: str
    requirement_keys: list[str]
    content: dict
    provenance: list[dict]
    status: str
    rejection_reason: str | None = None


class JobResponse(StrictModel):
    job_id: UUID
    kind: str
    state: str
    model_requested: str | None = None
    error_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    proposals: list[ProposalResponse]


class ApplyProposalRequest(StrictModel):
    case_id: UUID
    expected_edit_version: int


class ApplyProposalResponse(StrictModel):
    proposal_id: UUID
    case_id: UUID
    edit_version: int
    content: dict
    diff: list[dict]


class ConfirmSourcesRequest(StrictModel):
    source_names: list[str]


class ConfirmSourcesResponse(StrictModel):
    entity_id: UUID
    edit_version: int
    content: dict


class DraftRunRequest(StrictModel):
    environment_revision_id: UUID | None = None
    idempotency_key: str
    gate_profile: str = "strict"


class DraftRunResponse(StrictModel):
    run_id: UUID
    snapshot_digest: str
    provisional: bool = True
    blocked: bool
    planned_executions: int


def _parse_if_match(request: Request) -> int:
    raw = request.headers.get("if-match")
    if raw is None or raw.strip() == "":
        raise ApiError(428, ErrorCode.INPUT_INVALID, "Thiếu If-Match cho draft")
    cleaned = raw.strip()
    if cleaned.startswith("W/"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip().strip('"')
    try:
        return int(cleaned)
    except ValueError as error:
        raise ApiError(422, ErrorCode.INPUT_INVALID, "If-Match phải là edit version") from error


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


def _job_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        kind=job.kind,
        state=job.state,
        model_requested=job.model_requested,
        error_reason=job.error_reason,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        proposals=[
            ProposalResponse(
                proposal_id=proposal.proposal_id,
                job_id=proposal.job_id,
                title=proposal.title,
                case_kind=proposal.case_kind,
                requirement_keys=proposal.requirement_keys,
                content=proposal.content,
                provenance=proposal.provenance,
                status=proposal.status,
                rejection_reason=proposal.rejection_reason,
            )
            for proposal in job.proposals
        ],
    )


@router.post("/workspaces/{workspace_id}/authoring-jobs", response_model=JobResponse)
async def create_authoring_job(request: Request, workspace_id: UUID, payload: AuthoringJobRequest) -> JobResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        job = await runtime.authoring.create_job(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            goal=payload.goal,
            url=payload.url,
            expectations=payload.expectations,
            requirement_keys=payload.requirement_keys,
            sources=[item.model_dump(mode="json") for item in payload.sources],
            model_requested=payload.model_requested,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _job_response(job)


@router.get("/workspaces/{workspace_id}/jobs/{job_id}", response_model=JobResponse)
async def get_job(request: Request, workspace_id: UUID, job_id: UUID) -> JobResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        job = await runtime.authoring.get_job(workspace_id=workspace_id, principal_id=principal.user_id, job_id=job_id)
    except IdentityError as error:
        raise to_api_error(error) from error
    return _job_response(job)


@router.post("/workspaces/{workspace_id}/proposals/{proposal_id}/apply", response_model=ApplyProposalResponse)
async def apply_proposal(
    request: Request, workspace_id: UUID, proposal_id: UUID, payload: ApplyProposalRequest
) -> ApplyProposalResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    expected = _parse_if_match(request)
    try:
        outcome = await runtime.authoring.apply_proposal(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            proposal_id=proposal_id,
            case_id=payload.case_id,
            expected_edit_version=expected,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ApplyProposalResponse(
        proposal_id=outcome.proposal_id,
        case_id=outcome.case_id,
        edit_version=outcome.edit_version,
        content=outcome.content,
        diff=outcome.diff,
    )


@router.post(
    "/workspaces/{workspace_id}/cases/{case_id}/draft/confirm-sources",
    response_model=ConfirmSourcesResponse,
)
async def confirm_sources(
    request: Request, workspace_id: UUID, case_id: UUID, payload: ConfirmSourcesRequest
) -> ConfirmSourcesResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    expected = _parse_if_match(request)
    try:
        draft = await runtime.authoring.confirm_sources(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            case_id=case_id,
            source_names=payload.source_names,
            expected_edit_version=expected,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ConfirmSourcesResponse(entity_id=draft.entity_id, edit_version=draft.edit_version, content=draft.content)


@router.post("/workspaces/{workspace_id}/cases/{case_id}/draft/run", response_model=DraftRunResponse)
async def run_draft(request: Request, workspace_id: UUID, case_id: UUID, payload: DraftRunRequest) -> DraftRunResponse:
    principal = await _require(request, workspace_id, Permission.RUN_SUBMIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    draft = await runtime.revisions.get_draft(
        workspace_id=workspace_id, principal_id=principal.user_id, case_id=case_id
    )
    if draft is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Chưa có draft để chạy thử")
    outcome = await runtime.runs.submit_draft(
        DraftSubmitRequest(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            idempotency_key=payload.idempotency_key,
            case_id=case_id,
            content=draft.content,
            environment_revision_id=payload.environment_revision_id,
            gate_profile=payload.gate_profile,
        )
    )
    return DraftRunResponse(
        run_id=outcome.run_id,
        snapshot_digest=outcome.snapshot_digest,
        provisional=True,
        blocked=outcome.blocked,
        planned_executions=outcome.planned_executions,
    )
