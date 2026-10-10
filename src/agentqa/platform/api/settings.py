from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Request

from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import authenticate, enforce_browser_guard, get_runtime, to_api_error
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_API
from agentqa.platform.storage.scope import set_scope

router = APIRouter(prefix="/api/v1", tags=["settings"])


class CredentialReferenceResponse(StrictModel):
    credential_ref: str
    version: int
    kind: str
    status: str
    algorithm: str | None = None
    rotated_from: UUID | None = None


class CredentialReferenceListResponse(StrictModel):
    items: list[CredentialReferenceResponse]


class CredentialReferenceCreateRequest(StrictModel):
    credential_ref: str
    env_var_name: str


class CredentialRotateRequest(StrictModel):
    value: str


class CredentialRevokeRequest(StrictModel):
    reason: str


class CredentialVersionResponse(StrictModel):
    credential_ref: str
    version: int
    status: str


class CredentialRevokeResponse(StrictModel):
    credential_ref: str
    revoked_versions: int


async def _require_owner(request: Request, workspace_id: UUID, *, mutating: bool = True):
    principal = await authenticate(request)
    runtime = get_runtime(request)
    try:
        await runtime.authorization.require(
            workspace_id=workspace_id, user_id=principal.user_id, permission=Permission.SETTINGS_MANAGE
        )
    except IdentityError as error:
        raise to_api_error(error) from error
    if mutating:
        enforce_browser_guard(request, principal)
    return principal


@router.get("/workspaces/{workspace_id}/credential-references", response_model=CredentialReferenceListResponse)
async def list_credential_references(request: Request, workspace_id: UUID) -> CredentialReferenceListResponse:
    principal = await _require_owner(request, workspace_id, mutating=False)
    runtime = get_runtime(request)
    factory = create_session_factory(runtime.engines[ROLE_API])
    async with factory() as session, session.begin():
        await set_scope(session, principal_id=principal.user_id, workspace_id=workspace_id)
        rows = (
            await session.execute(
                sa.select(
                    tables.credential_records.c.credential_ref,
                    tables.credential_records.c.version,
                    tables.credential_records.c.kind,
                    tables.credential_records.c.status,
                    tables.credential_records.c.algorithm,
                    tables.credential_records.c.rotated_from,
                )
                .where(tables.credential_records.c.workspace_id == workspace_id)
                .order_by(
                    tables.credential_records.c.credential_ref,
                    tables.credential_records.c.version,
                )
            )
        ).all()
    return CredentialReferenceListResponse(
        items=[
            CredentialReferenceResponse(
                credential_ref=row.credential_ref,
                version=row.version,
                kind=row.kind,
                status=row.status,
                algorithm=row.algorithm,
                rotated_from=row.rotated_from,
            )
            for row in rows
        ]
    )


@router.post("/workspaces/{workspace_id}/credential-references", response_model=CredentialVersionResponse)
async def create_credential_reference(
    request: Request, workspace_id: UUID, body: CredentialReferenceCreateRequest
) -> CredentialVersionResponse:
    principal = await _require_owner(request, workspace_id)
    runtime = get_runtime(request)
    factory = create_session_factory(runtime.engines[ROLE_API])
    try:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=principal.user_id, workspace_id=workspace_id)
            record = await runtime.credentials.create_env_reference(
                session,
                workspace_id=workspace_id,
                credential_ref=body.credential_ref,
                env_var_name=body.env_var_name,
                actor=principal.username,
            )
    except SecurityError as error:
        raise to_api_error(error) from error
    return CredentialVersionResponse(credential_ref=record.credential_ref, version=record.version, status=record.status)


@router.post(
    "/workspaces/{workspace_id}/credential-references/{credential_ref}/rotate",
    response_model=CredentialVersionResponse,
)
async def rotate_credential_reference(
    request: Request, workspace_id: UUID, credential_ref: str, body: CredentialRotateRequest
) -> CredentialVersionResponse:
    principal = await _require_owner(request, workspace_id)
    runtime = get_runtime(request)
    factory = create_session_factory(runtime.engines[ROLE_API])
    try:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=principal.user_id, workspace_id=workspace_id)
            record = await runtime.credentials.rotate(
                session,
                workspace_id=workspace_id,
                credential_ref=credential_ref,
                plaintext=body.value,
                actor=principal.username,
            )
    except SecurityError as error:
        raise to_api_error(error) from error
    return CredentialVersionResponse(credential_ref=record.credential_ref, version=record.version, status=record.status)


@router.post(
    "/workspaces/{workspace_id}/credential-references/{credential_ref}/revoke",
    response_model=CredentialRevokeResponse,
)
async def revoke_credential_reference(
    request: Request, workspace_id: UUID, credential_ref: str, body: CredentialRevokeRequest
) -> CredentialRevokeResponse:
    principal = await _require_owner(request, workspace_id)
    runtime = get_runtime(request)
    factory = create_session_factory(runtime.engines[ROLE_API])
    try:
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=principal.user_id, workspace_id=workspace_id)
            count = await runtime.credentials.revoke_reference(
                session,
                workspace_id=workspace_id,
                credential_ref=credential_ref,
                reason=body.reason,
                actor=principal.username,
            )
    except SecurityError as error:
        raise to_api_error(error) from error
    return CredentialRevokeResponse(credential_ref=credential_ref, revoked_versions=count)
