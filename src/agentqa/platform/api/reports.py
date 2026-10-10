from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["reports"])

MEDIA_BY_FORMAT = {
    "json": "application/json",
    "html": "text/html; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "jsonl": "application/x-ndjson",
    "junit": "application/xml; charset=utf-8",
}


class ReportCreateRequest(StrictModel):
    format: str = "json"


class ReportResponse(StrictModel):
    report_id: UUID
    run_id: UUID
    format: str
    artifact_id: UUID
    digest: str | None = None
    media_type: str
    created_at: datetime


class ReportListResponse(StrictModel):
    items: list[ReportResponse]


class DiagnosticResponse(StrictModel):
    diagnostic_id: UUID
    run_id: UUID
    state: str
    label: str
    explanation: str | None = None
    confidence: str | None = None
    evidence_refs: list[str] = []
    model_call_id: UUID | None = None
    created_at: datetime


class DiagnosticListResponse(StrictModel):
    items: list[DiagnosticResponse]


class IssuePackageResponse(StrictModel):
    package_id: UUID
    run_id: UUID
    artifact_id: UUID
    digest: str | None = None
    preview: dict[str, Any]
    created_at: datetime


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


def _report_response(view) -> ReportResponse:
    return ReportResponse(
        report_id=view.report_id,
        run_id=view.run_id,
        format=view.format,
        artifact_id=view.artifact_id,
        digest=view.digest,
        media_type=view.media_type,
        created_at=view.created_at,
    )


@router.post("/workspaces/{workspace_id}/runs/{run_id}/reports", status_code=201, response_model=ReportResponse)
async def create_report(
    request: Request, workspace_id: UUID, run_id: UUID, body: ReportCreateRequest
) -> ReportResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        view = await runtime.reports.create(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            run_id=run_id,
            format=body.format,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _report_response(view)


@router.get("/workspaces/{workspace_id}/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_reports(request: Request, workspace_id: UUID, run_id: UUID) -> ReportListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    views = await runtime.reports.list_for_run(workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id)
    if views is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return ReportListResponse(items=[_report_response(view) for view in views])


@router.get("/workspaces/{workspace_id}/reports/{report_id}/content")
async def download_report(request: Request, workspace_id: UUID, report_id: UUID) -> Response:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        view, payload = await runtime.reports.download(
            workspace_id=workspace_id, principal_id=principal.user_id, report_id=report_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    media = MEDIA_BY_FORMAT.get(view.format, view.media_type)
    return Response(
        content=payload,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="report-{view.report_id}.{view.format}"',
            "X-Content-Digest": view.digest or "",
        },
    )


@router.post(
    "/workspaces/{workspace_id}/runs/{run_id}/issue-packages", status_code=201, response_model=IssuePackageResponse
)
async def create_issue_package(request: Request, workspace_id: UUID, run_id: UUID) -> IssuePackageResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        view = await runtime.reports.create_issue_package(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            run_id=run_id,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return IssuePackageResponse(
        package_id=view.package_id,
        run_id=view.run_id,
        artifact_id=view.artifact_id,
        digest=view.digest,
        preview=view.preview,
        created_at=view.created_at,
    )


@router.get("/workspaces/{workspace_id}/issue-packages/{package_id}/content")
async def download_issue_package(request: Request, workspace_id: UUID, package_id: UUID) -> Response:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        artifact_id, payload = await runtime.reports.download_issue_package(
            workspace_id=workspace_id, principal_id=principal.user_id, package_id=package_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="issue-package-{package_id}.json"',
            "X-Artifact-Id": str(artifact_id),
        },
    )


@router.post("/workspaces/{workspace_id}/runs/{run_id}/diagnostics", status_code=201, response_model=DiagnosticResponse)
async def create_diagnostic(request: Request, workspace_id: UUID, run_id: UUID) -> DiagnosticResponse:
    principal = await _require(request, workspace_id, Permission.RUN_SUBMIT)
    runtime = get_runtime(request)
    try:
        view = await runtime.diagnostics.create(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            run_id=run_id,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return DiagnosticResponse(
        diagnostic_id=view.diagnostic_id,
        run_id=view.run_id,
        state=view.state,
        label=view.label,
        explanation=view.explanation,
        confidence=format(view.confidence, "f") if view.confidence is not None else None,
        evidence_refs=view.evidence_refs,
        model_call_id=view.model_call_id,
        created_at=view.created_at,
    )


@router.get("/workspaces/{workspace_id}/runs/{run_id}/diagnostics", response_model=DiagnosticListResponse)
async def list_diagnostics(request: Request, workspace_id: UUID, run_id: UUID) -> DiagnosticListResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    views = await runtime.diagnostics.list_for_run(
        workspace_id=workspace_id, principal_id=principal.user_id, run_id=run_id
    )
    if views is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Không tìm thấy run")
    return DiagnosticListResponse(
        items=[
            DiagnosticResponse(
                diagnostic_id=view.diagnostic_id,
                run_id=view.run_id,
                state=view.state,
                label=view.label,
                explanation=view.explanation,
                confidence=format(view.confidence, "f") if view.confidence is not None else None,
                evidence_refs=view.evidence_refs,
                model_call_id=view.model_call_id,
                created_at=view.created_at,
            )
            for view in views
        ]
    )
