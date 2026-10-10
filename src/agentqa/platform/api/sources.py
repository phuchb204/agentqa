from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile

from agentqa.contracts.case import SourceAnchor
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.extraction.service import ExtractionError
from agentqa.platform.extraction.validation import MAX_UPLOAD_BYTES
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.sources.service import SourceRevisionView, SourceSegmentView

router = APIRouter(prefix="/api/v1", tags=["sources"])


class SourceCreateRequest(StrictModel):
    logical_key: str


class SourceEntityResponse(StrictModel):
    id: UUID
    logical_key: str


class SourceRevisionResponse(StrictModel):
    revision_id: UUID
    source_id: UUID
    logical_key: str
    revision_no: int
    filename: str
    media_type: str
    size_bytes: int
    file_digest: str
    privacy_class: str
    state: str
    unextractable_reason: str | None = None
    created_at: datetime
    segment_count: int


class SourceSegmentResponse(StrictModel):
    ordinal: int
    anchor: SourceAnchor
    text: str
    text_digest: str
    privacy: str


class SourceDetailResponse(StrictModel):
    revision: SourceRevisionResponse
    segments: list[SourceSegmentResponse]


def _revision_response(view) -> SourceRevisionResponse:
    return SourceRevisionResponse(
        revision_id=view.revision_id,
        source_id=view.source_id,
        logical_key=view.logical_key,
        revision_no=view.revision_no,
        filename=view.filename,
        media_type=view.media_type,
        size_bytes=view.size_bytes,
        file_digest=view.file_digest,
        privacy_class=view.privacy_class,
        state=view.state,
        unextractable_reason=view.unextractable_reason,
        created_at=view.created_at,
        segment_count=view.segment_count,
    )


def _detail_response(view: SourceRevisionView, segments: list[SourceSegmentView]) -> SourceDetailResponse:
    return SourceDetailResponse(
        revision=_revision_response(view),
        segments=[
            SourceSegmentResponse(
                ordinal=segment.ordinal,
                anchor=SourceAnchor.model_validate(segment.anchor),
                text=segment.text,
                text_digest=segment.text_digest,
                privacy=segment.privacy,
            )
            for segment in segments
        ],
    )


async def _require(request: Request, workspace_id: UUID, permission: Permission):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(workspace_id=workspace_id, user_id=principal.user_id, permission=permission)
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


@router.post("/workspaces/{workspace_id}/sources", response_model=SourceEntityResponse)
async def create_source(request: Request, workspace_id: UUID, payload: SourceCreateRequest) -> SourceEntityResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        source = await runtime.sources.create_source(
            workspace_id=workspace_id, principal_id=principal.user_id, logical_key=payload.logical_key
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return SourceEntityResponse(id=source.id, logical_key=source.logical_key)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceEntityResponse])
async def list_sources(request: Request, workspace_id: UUID) -> list[SourceEntityResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    sources = await runtime.sources.list_sources(workspace_id=workspace_id, principal_id=principal.user_id)
    return [SourceEntityResponse(id=source.id, logical_key=source.logical_key) for source in sources]


@router.post("/workspaces/{workspace_id}/sources/{source_id}/revisions", response_model=SourceDetailResponse)
async def upload_source_revision(
    request: Request,
    workspace_id: UUID,
    source_id: UUID,
    logical_key: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> SourceDetailResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        outcome = await runtime.sources.upload_revision(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            source_id=source_id,
            filename=file.filename or logical_key,
            media_type=file.content_type or "application/octet-stream",
            payload=payload,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    except ExtractionError as error:
        raise ApiError(500, ErrorCode.STORAGE_UNAVAILABLE, "Không thể trích xuất nội dung file") from error
    return _detail_response(outcome.revision, outcome.segments)


@router.get("/workspaces/{workspace_id}/sources/{source_id}/revisions", response_model=list[SourceRevisionResponse])
async def list_source_revisions(request: Request, workspace_id: UUID, source_id: UUID) -> list[SourceRevisionResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        revisions = await runtime.sources.list_revisions(
            workspace_id=workspace_id, principal_id=principal.user_id, source_id=source_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return [_revision_response(revision) for revision in revisions]


@router.get(
    "/workspaces/{workspace_id}/sources/{source_id}/revisions/{revision_no}",
    response_model=SourceDetailResponse,
)
async def get_source_revision(
    request: Request, workspace_id: UUID, source_id: UUID, revision_no: int
) -> SourceDetailResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    runtime = get_runtime(request)
    try:
        view, segments = await runtime.sources.get_revision(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            source_id=source_id,
            revision_no=revision_no,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _detail_response(view, segments)


@router.post("/workspaces/{workspace_id}/sources/{source_id}/extract", response_model=SourceDetailResponse)
async def extract_source(request: Request, workspace_id: UUID, source_id: UUID) -> SourceDetailResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    try:
        outcome = await runtime.sources.extract_pending(
            workspace_id=workspace_id, principal_id=principal.user_id, source_id=source_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    except ExtractionError as error:
        raise ApiError(500, ErrorCode.STORAGE_UNAVAILABLE, "Không thể trích xuất nội dung file") from error
    return _detail_response(outcome.revision, outcome.segments)
