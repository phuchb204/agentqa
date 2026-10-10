from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.revisions.service import RevisionService, validate_content

router = APIRouter(prefix="/api/v1", tags=["revisions"])

ENTITY_KINDS = ("requirement", "suite", "dataset", "fixture")


class EntityCreateRequest(StrictModel):
    logical_key: str


class ApplicationCreateRequest(StrictModel):
    slug: str
    name: str


class EntityResponse(StrictModel):
    id: UUID
    logical_key: str


class DraftPatchRequest(StrictModel):
    content: dict


class DraftResponse(StrictModel):
    entity_id: UUID
    edit_version: int
    content: dict
    updated_by: str
    updated_at: datetime


class DraftValidateResponse(StrictModel):
    valid: bool
    field_errors: list[dict] = []


class ContentRequest(StrictModel):
    content: dict


class PromotionResponse(StrictModel):
    revision_id: UUID
    entity_id: UUID
    revision_no: int
    content_digest: str
    promoted_by: str
    promoted_at: datetime
    supersedes: UUID | None = None


class RevisionResponse(StrictModel):
    revision_id: UUID
    entity_id: UUID
    revision_no: int
    content: dict
    content_digest: str
    lifecycle: str
    author: str
    promoted_by: str | None = None
    promoted_at: datetime | None = None
    supersedes: UUID | None = None
    archived_at: datetime | None = None


class BundleResponse(StrictModel):
    schema_version: str
    kind: str
    revisions: list[dict]


class BundleImportRequest(StrictModel):
    bundle: dict


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


def _service(request: Request) -> RevisionService:
    return get_runtime(request).revisions


def _to_promotion(receipt) -> PromotionResponse:
    return PromotionResponse(
        revision_id=receipt.revision_id,
        entity_id=receipt.entity_id,
        revision_no=receipt.revision_no,
        content_digest=receipt.content_digest,
        promoted_by=receipt.promoted_by,
        promoted_at=receipt.promoted_at,
        supersedes=receipt.supersedes,
    )


def _to_revision(view) -> RevisionResponse:
    return RevisionResponse(
        revision_id=view.revision_id,
        entity_id=view.entity_id,
        revision_no=view.revision_no,
        content=view.content,
        content_digest=view.content_digest,
        lifecycle=view.lifecycle,
        author=view.author,
        promoted_by=view.promoted_by,
        promoted_at=view.promoted_at,
        supersedes=view.supersedes,
        archived_at=view.archived_at,
    )


@router.post("/workspaces/{workspace_id}/cases", response_model=EntityResponse)
async def create_case(request: Request, workspace_id: UUID, payload: EntityCreateRequest) -> EntityResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    try:
        entity = await _service(request).create_entity(
            workspace_id=workspace_id, principal_id=principal.user_id, kind="case", logical_key=payload.logical_key
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return EntityResponse(id=entity.id, logical_key=entity.logical_key)


@router.get("/workspaces/{workspace_id}/cases", response_model=list[EntityResponse])
async def list_cases(
    request: Request, workspace_id: UUID, logical_key: str | None = None, limit: int = 50
) -> list[EntityResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    entities = await _service(request).list_entities(
        workspace_id=workspace_id, principal_id=principal.user_id, kind="case", logical_key=logical_key, limit=limit
    )
    return [EntityResponse(id=entity.id, logical_key=entity.logical_key) for entity in entities]


@router.post("/workspaces/{workspace_id}/applications", response_model=EntityResponse)
async def create_application(request: Request, workspace_id: UUID, payload: ApplicationCreateRequest) -> EntityResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    try:
        entity = await _service(request).create_entity(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            kind="environment",
            logical_key=payload.slug,
            name=payload.name,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return EntityResponse(id=entity.id, logical_key=entity.logical_key)


@router.get("/workspaces/{workspace_id}/applications", response_model=list[EntityResponse])
async def list_applications(request: Request, workspace_id: UUID) -> list[EntityResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    entities = await _service(request).list_entities(
        workspace_id=workspace_id, principal_id=principal.user_id, kind="environment"
    )
    return [EntityResponse(id=entity.id, logical_key=entity.logical_key) for entity in entities]


@router.post("/workspaces/{workspace_id}/{kind}s", response_model=EntityResponse)
async def create_entity(
    request: Request, workspace_id: UUID, kind: str, payload: EntityCreateRequest
) -> EntityResponse:
    if kind not in ENTITY_KINDS:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Kind không hỗ trợ")
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    try:
        entity = await _service(request).create_entity(
            workspace_id=workspace_id, principal_id=principal.user_id, kind=kind, logical_key=payload.logical_key
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return EntityResponse(id=entity.id, logical_key=entity.logical_key)


@router.get("/workspaces/{workspace_id}/{kind}s", response_model=list[EntityResponse])
async def list_entities(
    request: Request, workspace_id: UUID, kind: str, logical_key: str | None = None, limit: int = 50
) -> list[EntityResponse]:
    if kind not in ENTITY_KINDS:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Kind không hỗ trợ")
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    entities = await _service(request).list_entities(
        workspace_id=workspace_id, principal_id=principal.user_id, kind=kind, logical_key=logical_key, limit=limit
    )
    return [EntityResponse(id=entity.id, logical_key=entity.logical_key) for entity in entities]


@router.get("/workspaces/{workspace_id}/cases/{case_id}/draft", response_model=None)
async def get_case_draft(request: Request, workspace_id: UUID, case_id: UUID) -> Response:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    draft = await _service(request).get_draft(
        workspace_id=workspace_id, principal_id=principal.user_id, case_id=case_id
    )
    if draft is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Chưa có draft")
    body = DraftResponse(
        entity_id=draft.entity_id,
        edit_version=draft.edit_version,
        content=draft.content,
        updated_by=draft.updated_by,
        updated_at=draft.updated_at,
    )
    return Response(
        content=body.model_dump_json(),
        media_type="application/json",
        headers={"ETag": f'"{draft.edit_version}"'},
    )


@router.patch("/workspaces/{workspace_id}/cases/{case_id}/draft", response_model=DraftResponse)
async def patch_case_draft(
    request: Request, workspace_id: UUID, case_id: UUID, payload: DraftPatchRequest
) -> DraftResponse:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    expected = _parse_if_match(request)
    try:
        draft = await _service(request).save_draft(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            case_id=case_id,
            content=payload.content,
            expected_edit_version=expected,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return DraftResponse(
        entity_id=draft.entity_id,
        edit_version=draft.edit_version,
        content=draft.content,
        updated_by=draft.updated_by,
        updated_at=draft.updated_at,
    )


@router.post("/workspaces/{workspace_id}/cases/{case_id}/draft/validate", response_model=DraftValidateResponse)
async def validate_case_draft(
    request: Request, workspace_id: UUID, case_id: UUID, payload: ContentRequest | None = None
) -> DraftValidateResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    content = payload.content if payload is not None else None
    if content is None:
        draft = await _service(request).get_draft(
            workspace_id=workspace_id, principal_id=principal.user_id, case_id=case_id
        )
        if draft is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "Chưa có draft")
        content = draft.content
    try:
        validate_content("case", content)
    except IdentityError as error:
        raise to_api_error(error) from error
    except AgentQAValidationError as error:
        return DraftValidateResponse(
            valid=False,
            field_errors=[
                {"path": list(field.path), "code": field.code.value, "message": field.message} for field in error.errors
            ],
        )
    return DraftValidateResponse(valid=True)


@router.post("/workspaces/{workspace_id}/cases/{case_id}/draft/promote", response_model=PromotionResponse)
async def promote_case_draft(request: Request, workspace_id: UUID, case_id: UUID) -> PromotionResponse:
    principal = await _require(request, workspace_id, Permission.CASE_PROMOTE)
    enforce_browser_guard(request, principal)
    expected = _parse_if_match(request)
    try:
        receipt = await _service(request).promote_draft(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            case_id=case_id,
            expected_edit_version=expected,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_promotion(receipt)


@router.get("/workspaces/{workspace_id}/cases/{case_id}/revisions", response_model=list[RevisionResponse])
async def list_case_revisions(request: Request, workspace_id: UUID, case_id: UUID) -> list[RevisionResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    revisions = await _service(request).list_revisions(
        workspace_id=workspace_id, principal_id=principal.user_id, kind="case", entity_id=case_id
    )
    return [_to_revision(view) for view in revisions]


@router.post(
    "/workspaces/{workspace_id}/cases/{case_id}/revisions/{revision_id}/archive",
    response_model=RevisionResponse,
)
async def archive_case_revision(
    request: Request, workspace_id: UUID, case_id: UUID, revision_id: UUID
) -> RevisionResponse:
    principal = await _require(request, workspace_id, Permission.CASE_PROMOTE)
    enforce_browser_guard(request, principal)
    try:
        view = await _service(request).archive_revision(
            workspace_id=workspace_id, principal_id=principal.user_id, kind="case", revision_id=revision_id
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_revision(view)


@router.post(
    "/workspaces/{workspace_id}/applications/{application_id}/environment-revisions",
    response_model=PromotionResponse,
)
async def promote_environment_revision(
    request: Request, workspace_id: UUID, application_id: UUID, payload: ContentRequest
) -> PromotionResponse:
    principal = await _require(request, workspace_id, Permission.CASE_PROMOTE)
    enforce_browser_guard(request, principal)
    try:
        receipt = await _service(request).promote_content(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            kind="environment",
            entity_id=application_id,
            content=payload.content,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_promotion(receipt)


@router.get(
    "/workspaces/{workspace_id}/applications/{application_id}/environment-revisions",
    response_model=list[RevisionResponse],
)
async def list_environment_revisions(
    request: Request, workspace_id: UUID, application_id: UUID
) -> list[RevisionResponse]:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    revisions = await _service(request).list_revisions(
        workspace_id=workspace_id, principal_id=principal.user_id, kind="environment", entity_id=application_id
    )
    return [_to_revision(view) for view in revisions]


@router.post("/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions", response_model=PromotionResponse)
async def promote_entity_revision(
    request: Request, workspace_id: UUID, kind: str, entity_id: UUID, payload: ContentRequest
) -> PromotionResponse:
    if kind not in ENTITY_KINDS:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Kind không hỗ trợ")
    principal = await _require(request, workspace_id, Permission.CASE_PROMOTE)
    enforce_browser_guard(request, principal)
    try:
        receipt = await _service(request).promote_content(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            kind=kind,
            entity_id=entity_id,
            content=payload.content,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return _to_promotion(receipt)


@router.get("/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions", response_model=list[RevisionResponse])
async def list_entity_revisions(
    request: Request, workspace_id: UUID, kind: str, entity_id: UUID
) -> list[RevisionResponse]:
    if kind not in ENTITY_KINDS:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Kind không hỗ trợ")
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    revisions = await _service(request).list_revisions(
        workspace_id=workspace_id, principal_id=principal.user_id, kind=kind, entity_id=entity_id
    )
    return [_to_revision(view) for view in revisions]


@router.get("/workspaces/{workspace_id}/revisions/export", response_model=BundleResponse)
async def export_revisions(request: Request, workspace_id: UUID, kind: str) -> BundleResponse:
    principal = await _require(request, workspace_id, Permission.WORKSPACE_READ)
    try:
        bundle = await _service(request).export_bundle(
            workspace_id=workspace_id, principal_id=principal.user_id, kind=kind
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return BundleResponse(**bundle)


@router.post("/workspaces/{workspace_id}/revisions/import", response_model=list[PromotionResponse])
async def import_revisions(
    request: Request, workspace_id: UUID, payload: BundleImportRequest
) -> list[PromotionResponse]:
    principal = await _require(request, workspace_id, Permission.CASE_EDIT)
    enforce_browser_guard(request, principal)
    try:
        receipts = await _service(request).import_bundle(
            workspace_id=workspace_id,
            principal_id=principal.user_id,
            actor=principal.username,
            bundle=payload.bundle,
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    return [_to_promotion(receipt) for receipt in receipts]
