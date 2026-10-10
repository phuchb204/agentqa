from __future__ import annotations

from hashlib import sha256
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["imports"])


class ImportRequest(StrictModel):
    format: Literal["yaml", "json"]
    content: str


class PromotionSummary(StrictModel):
    revision_id: UUID
    entity_id: UUID
    revision_no: int
    content_digest: str


class ImportResponse(StrictModel):
    imported: list[PromotionSummary]


class ExportRequest(StrictModel):
    kinds: list[str] | None = None
    format: Literal["yaml", "json"] = "yaml"


class ExportResponse(StrictModel):
    schema_version: str
    format: str
    content: str
    digest: str


class PlannedExecutionResponse(StrictModel):
    execution_key: str
    case_logical_key: str
    case_revision_id: UUID | None = None
    dataset_row_index: int | None = None
    parameters: dict


class BindResponse(StrictModel):
    suite_revision_id: UUID
    suite_logical_key: str
    fixture_refs: list[str]
    executions: list[PlannedExecutionResponse]
    facts: list[str]


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/imports", response_model=ImportResponse)
async def import_bundle(request: Request, workspace_id: UUID, payload: ImportRequest) -> ImportResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        receipts = await runtime.bundles.import_text(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            text=payload.content,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return ImportResponse(
        imported=[
            PromotionSummary(
                revision_id=receipt.revision_id,
                entity_id=receipt.entity_id,
                revision_no=receipt.revision_no,
                content_digest=receipt.content_digest,
            )
            for receipt in receipts
        ]
    )


@router.post("/workspaces/{workspace_id}/exports", response_model=ExportResponse)
async def export_bundle(request: Request, workspace_id: UUID, payload: ExportRequest) -> ExportResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        bundle = await runtime.bundles.export_workspace(
            workspace_id=workspace_id, principal_id=principal.user_id, kinds=payload.kinds
        )
        text = runtime.bundles.export_text(bundle, format=payload.format)
    except IdentityError as error:
        raise to_api_error(error) from error
    return ExportResponse(
        schema_version=bundle["schema_version"],
        format=payload.format,
        content=text,
        digest=sha256(text.encode("utf-8")).hexdigest(),
    )


@router.post(
    "/workspaces/{workspace_id}/suites/{suite_id}/revisions/{revision_id}/bind",
    response_model=BindResponse,
)
async def bind_suite_revision(request: Request, workspace_id: UUID, suite_id: UUID, revision_id: UUID) -> BindResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        result = await runtime.suites.bind(
            workspace_id=workspace_id, principal_id=principal.user_id, suite_revision_id=revision_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return BindResponse(
        suite_revision_id=result.suite_revision_id,
        suite_logical_key=result.suite_logical_key,
        fixture_refs=result.fixture_refs,
        executions=[
            PlannedExecutionResponse(
                execution_key=execution.execution_key,
                case_logical_key=execution.case_logical_key,
                case_revision_id=execution.case_revision_id,
                dataset_row_index=execution.dataset_row_index,
                parameters=execution.parameters,
            )
            for execution in result.executions
        ],
        facts=result.facts,
    )
