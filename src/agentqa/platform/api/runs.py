from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Request

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.observation import Modality
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.healing import HealingService
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.runs.read_models import RunReadModel
from agentqa.platform.runs.service import SubmitRequest
from agentqa.platform.storage.roles import ROLE_API

router = APIRouter(prefix="/api/v1", tags=["runs"])


class SubmitRunRequest(StrictModel):
    case_revision_ids: list[UUID] = []
    suite_revision_id: UUID | None = None
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


class RunListItemResponse(StrictModel):
    run_id: UUID
    status: str
    verdict: str | None = None
    gate: str | None = None
    annotations: list[str] = []
    reasons: list[str] = []
    policy: str | None = None
    observation_mode: str | None = None
    environment_revision_id: UUID | None = None
    created_at: datetime
    finalized_at: datetime | None = None
    executions: list[ExecutionStateResponse] = []


class RunListResponse(StrictModel):
    items: list[RunListItemResponse]
    next_cursor: str | None = None
    total: int


class AssertionDetailResponse(StrictModel):
    checkpoint_id: str
    assertion_id: str
    result: str
    proof: dict


class ExecutionDetailResponse(StrictModel):
    execution_id: UUID
    logical_key: str
    status: str
    verdict: str | None = None
    assertions: list[AssertionDetailResponse] = []


class ArtifactSummaryResponse(StrictModel):
    artifact_id: UUID
    kind: str
    state: str
    media_type: str | None = None
    digest: str | None = None
    redacted: bool
    unavailable_reason: str | None = None


class UsageSummaryResponse(StrictModel):
    state: str
    input_tokens: int
    output_tokens: int
    settled_calls: int
    unknown_calls: int
    cost_state: str
    cost_total: str | None = None
    cost_currency: str | None = None


class HealingRecordResponse(StrictModel):
    record_id: UUID
    run_id: UUID
    execution_id: UUID | None = None
    attempt_id: UUID | None = None
    actor: str
    node_id: str
    opportunity_id: str
    attempt_ref: str
    decision: str
    ranking: dict | None = None
    expected_signature: str | None = None
    actual_signature: str | None = None
    original_target: dict | None = None
    actual_target: dict | None = None
    dispatch_outcome: str | None = None
    guard_checks: list[str] = []
    postconditions_ok: bool | None = None
    refusal_reason: str | None = None
    error: str | None = None
    proposal: dict | None = None
    source_run_id: UUID | None = None
    case_id: UUID | None = None
    case_revision_id: UUID | None = None
    recorded_at: datetime


class HealingListResponse(StrictModel):
    items: list[HealingRecordResponse]


class SnapshotSummaryResponse(StrictModel):
    policy: str | None = None
    observation_mode: str | None = None
    gate_profile: str | None = None
    cache_profile: str | None = None
    calibration_ref: str | None = None
    budgets: dict | None = None
    content_digests: list[str] = []
    environment_revision: UUID | None = None
    provisional: bool = False


class RunDetailResponse(StrictModel):
    run_id: UUID
    status: str
    verdict: str | None = None
    gate: str | None = None
    reasons: list[str] = []
    annotations: list[str] = []
    terminal: bool
    snapshot: SnapshotSummaryResponse
    executions: list[ExecutionDetailResponse]
    controls: list[ControlStateResponse]
    artifacts: list[ArtifactSummaryResponse]
    usage: UsageSummaryResponse


class ConfigDiffResponse(StrictModel):
    field: str
    a: object | None = None
    b: object | None = None
    equal: bool


class ComparisonAssertionResponse(StrictModel):
    checkpoint_id: str
    assertion_id: str
    aligned: bool
    a_status: str | None = None
    b_status: str | None = None
    a_expected: str | None = None
    b_expected: str | None = None
    a_observed: str | None = None
    b_observed: str | None = None


class AlignmentResponse(StrictModel):
    logical_key: str
    aligned: bool
    reason: str | None = None
    a_status: str | None = None
    b_status: str | None = None
    a_verdict: str | None = None
    b_verdict: str | None = None
    assertions: list[ComparisonAssertionResponse] = []


class ComparisonMetricResponse(StrictModel):
    verdict: str | None = None
    status: str
    gate: str | None = None
    usage_state: str
    usage_input_tokens: int
    usage_output_tokens: int
    cost_state: str
    cost_total: str | None = None
    cost_currency: str | None = None


class ComparisonResponse(StrictModel):
    run_a: UUID
    run_b: UUID
    config_diff: list[ConfigDiffResponse]
    metrics: dict[str, ComparisonMetricResponse]
    alignment: list[AlignmentResponse]
    provenance: dict | None = None
    denominators: dict | None = None


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
                suite_revision_id=body.suite_revision_id,
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


@router.get("/workspaces/{workspace_id}/runs", response_model=RunListResponse)
async def list_runs(
    request: Request,
    workspace_id: UUID,
    status: str | None = None,
    verdict: str | None = None,
    healed: bool | None = None,
    policy: str | None = None,
    environment_revision_id: UUID | None = None,
    case_logical_key: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> RunListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    after = None
    if cursor:
        created_at, separator, run_id_text = cursor.partition("|")
        if separator != "|" or not created_at or not run_id_text:
            raise ApiError(422, ErrorCode.INPUT_INVALID, "Cursor không hợp lệ")
        try:
            UUID(run_id_text)
        except ValueError as error:
            raise ApiError(422, ErrorCode.INPUT_INVALID, "Cursor không hợp lệ") from error
        after = (created_at, run_id_text)
    result = await _read_model(request).run_list(
        workspace_id=workspace_id,
        principal_id=principal.user_id,
        status=status,
        verdict=verdict,
        healed=healed,
        policy=policy,
        environment_revision_id=environment_revision_id,
        case_logical_key=case_logical_key,
        date_from=date_from,
        date_to=date_to,
        after=after,
        limit=min(max(limit, 1), 100),
    )
    return RunListResponse.model_validate(result)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/detail", response_model=RunDetailResponse)
async def get_run_detail(request: Request, workspace_id: UUID, run_id: UUID) -> RunDetailResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    detail = await _read_model(request).run_detail(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if detail is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return RunDetailResponse.model_validate(detail)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/comparison", response_model=ComparisonResponse)
async def compare_runs(request: Request, workspace_id: UUID, run_id: UUID, against: UUID) -> ComparisonResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    comparison = await runtime.comparison.compare(
        workspace_id=workspace_id, principal_id=principal.user_id, run_a=run_id, run_b=against
    )
    if comparison is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run để so sánh")
    return ComparisonResponse.model_validate(comparison)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/healing", response_model=HealingListResponse)
async def list_run_healing(request: Request, workspace_id: UUID, run_id: UUID) -> HealingListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    items = await HealingService(runtime.engines[ROLE_API]).list_for_run(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if items is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return HealingListResponse(items=[HealingRecordResponse.model_validate(item) for item in items])
