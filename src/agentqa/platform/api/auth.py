from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import StrictModel
from agentqa.platform.api.deps import (
    SESSION_COOKIE,
    authenticate,
    enforce_browser_guard,
    enforce_origin,
    get_runtime,
    session_cookie_value,
    to_api_error,
)
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.security.taint import SecurityError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


class LoginRequest(StrictModel):
    username: str
    password: str


class BootstrapRequest(StrictModel):
    nonce: str


class TokenCreateRequest(StrictModel):
    name: str
    scopes: list[str] = []
    permission_flags: list[str] = []
    expires_at: datetime | None = None


class SessionResponse(StrictModel):
    user_id: UUID
    username: str
    csrf_token: str | None = None
    expires_at: datetime


class PrincipalResponse(StrictModel):
    user_id: UUID
    username: str
    session_id: UUID | None = None
    token_id: UUID | None = None


class TokenIssuedResponse(StrictModel):
    token_id: UUID
    token: str


class CsrfResponse(StrictModel):
    csrf_token: str


def _set_session_cookie(response: Response, request: Request, raw_token: str) -> None:
    runtime = get_runtime(request)
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=runtime.profile.origin_policy().secure_cookies,
        path="/",
    )


@router.post("/login", response_model=SessionResponse)
async def login(request: Request, payload: LoginRequest, response: Response) -> SessionResponse:
    enforce_origin(request)
    runtime = get_runtime(request)
    try:
        result = await runtime.sessions.login(username=payload.username, password=payload.password)
    except IdentityError as error:
        raise to_api_error(error) from error
    _set_session_cookie(response, request, result.raw_token)
    return SessionResponse(
        user_id=result.user_id, username=result.username, csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post("/local-bootstrap", response_model=SessionResponse)
async def local_bootstrap(request: Request, payload: BootstrapRequest, response: Response) -> SessionResponse:
    enforce_origin(request)
    runtime = get_runtime(request)
    owner = await runtime.users.first_user()
    if owner is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Chưa có owner local")
    try:
        result = await runtime.bootstrap.exchange(
            nonce=payload.nonce,
            origin=request.headers.get("origin"),
            request_host=request.headers.get("host"),
            client_host=request.client.host if request.client else None,
            owner_user_id=owner.id,
            owner_username=owner.username,
        )
    except (IdentityError, SecurityError) as error:
        raise to_api_error(error) from error
    _set_session_cookie(response, request, result.raw_token)
    return SessionResponse(
        user_id=result.user_id, username=result.username, csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post("/csrf", response_model=CsrfResponse)
async def refresh_csrf(request: Request) -> CsrfResponse:
    await authenticate(request)
    enforce_origin(request)
    raw_token = session_cookie_value(request)
    if raw_token is None:
        raise ApiError(400, ErrorCode.INPUT_INVALID, "Cần session cookie để lấy CSRF token")
    runtime = get_runtime(request)
    csrf_token = await runtime.sessions.refresh_csrf(raw_token)
    return CsrfResponse(csrf_token=csrf_token)


@router.get("/session", response_model=PrincipalResponse)
async def current_session(request: Request) -> PrincipalResponse:
    principal = await authenticate(request)
    return PrincipalResponse(
        user_id=principal.user_id,
        username=principal.username,
        session_id=principal.session_id,
        token_id=principal.token_id,
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    principal = await authenticate(request)
    enforce_browser_guard(request, principal)
    raw_token = session_cookie_value(request)
    if raw_token is None:
        raise ApiError(400, ErrorCode.INPUT_INVALID, "Logout cần session cookie")
    runtime = get_runtime(request)
    await runtime.sessions.logout(raw_token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/tokens", response_model=TokenIssuedResponse)
async def create_token(request: Request, payload: TokenCreateRequest) -> TokenIssuedResponse:
    principal = await authenticate(request)
    enforce_browser_guard(request, principal)
    runtime = get_runtime(request)
    issued = await runtime.tokens.create(
        user_id=principal.user_id,
        name=payload.name,
        scopes=tuple(payload.scopes),
        permission_flags=tuple(payload.permission_flags),
        expires_at=payload.expires_at,
    )
    return TokenIssuedResponse(token_id=issued.record.id, token=issued.raw_token)
