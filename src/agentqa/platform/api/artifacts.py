from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


class ArtifactResponse(StrictModel):
    artifact_id: UUID
    run_id: UUID | None = None
    kind: str
    state: str
    digest: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    retention: str
    redacted: bool
    unavailable_reason: str | None = None
    created_at: datetime
    available_at: datetime | None = None
    tombstoned_at: datetime | None = None


async def _require(request: Request, workspace_id: UUID):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.ARTIFACT_READ
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return principal


def _to_response(view) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=view.id,
        run_id=view.run_id,
        kind=view.kind,
        state=view.state,
        digest=view.digest,
        size_bytes=view.size_bytes,
        media_type=view.media_type,
        retention=view.retention,
        redacted=bool(getattr(view, "redacted", True)),
        unavailable_reason=view.unavailable_reason,
        created_at=view.created_at,
        available_at=view.available_at,
        tombstoned_at=view.tombstoned_at,
    )


@router.get("/workspaces/{workspace_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(request: Request, workspace_id: UUID, artifact_id: UUID) -> ArtifactResponse:
    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    try:
        view = await runtime.artifacts.get_authorized(
            workspace_id=workspace_id, principal_id=principal.user_id, artifact_id=artifact_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_response(view)


@router.get("/workspaces/{workspace_id}/artifacts/{artifact_id}/content")
async def get_artifact_content(request: Request, workspace_id: UUID, artifact_id: UUID) -> Response:
    principal = await _require(request, workspace_id)
    runtime = get_runtime(request)
    try:
        view = await runtime.artifacts.get_authorized(
            workspace_id=workspace_id, principal_id=principal.user_id, artifact_id=artifact_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    if view.state != "available":
        raise ApiError(
            410,
            ErrorCode.EVIDENCE_MISSING,
            f"Artifact không khả dụng: {view.unavailable_reason or view.state}",
        )
    try:
        payload = await runtime.artifacts.open_bytes(
            workspace_id=workspace_id, principal_id=principal.user_id, artifact_id=artifact_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return Response(content=payload, media_type=view.media_type or "application/octet-stream")
