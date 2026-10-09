from __future__ import annotations

from fastapi import Request

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.api.error_models import ApiError
from agentqa.platform.api.runtime import PlatformRuntime
from agentqa.platform.identity.models import IdentityError, Permission, Principal, require_permission
from agentqa.platform.security.origin import verify_csrf
from agentqa.platform.security.taint import SecurityError

SESSION_COOKIE = "agentqa_session"


def get_runtime(request: Request) -> PlatformRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise ApiError(503, ErrorCode.STORAGE_UNAVAILABLE, "Runtime chưa được cấu hình")
    return runtime


def to_api_error(error: Exception) -> ApiError:
    if isinstance(error, IdentityError):
        status = getattr(error, "status_code", None) or {
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.PERMISSION_DENIED: 403,
            ErrorCode.DUPLICATE_KEY: 409,
            ErrorCode.PROVIDER_AUTH: 401,
            ErrorCode.INPUT_INVALID: 422,
        }.get(error.code, 400)
        return ApiError(status, error.code, error.message)
    if isinstance(error, SecurityError):
        status = 403 if error.code in (ErrorCode.PERMISSION_DENIED, ErrorCode.SECRET_SERIALIZATION) else 422
        return ApiError(status, error.code, error.message)
    return ApiError(500, ErrorCode.VERIFICATION_ERROR, "Lỗi hệ thống")


async def authenticate(request: Request) -> Principal:
    runtime = get_runtime(request)
    header = request.headers.get("authorization")
    try:
        if header and header.lower().startswith("bearer "):
            return await runtime.tokens.authenticate(header[7:].strip())
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie:
            return await runtime.sessions.authenticate(cookie)
    except IdentityError as error:
        raise to_api_error(error) from error
    raise ApiError(401, ErrorCode.PERMISSION_DENIED, "Yêu cầu xác thực")


def enforce_origin(request: Request) -> None:
    runtime = get_runtime(request)
    try:
        runtime.profile.origin_policy().check(request.headers.get("origin"), request_host=request.headers.get("host"))
    except SecurityError as error:
        raise to_api_error(error) from error


def session_cookie_value(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def enforce_csrf(request: Request, principal: Principal) -> None:
    if principal.session_id is None:
        return
    try:
        verify_csrf(principal.csrf_hash, request.headers.get("x-csrf-token"))
    except SecurityError as error:
        raise to_api_error(error) from error


def enforce_browser_guard(request: Request, principal: Principal) -> None:
    if principal.session_id is None:
        return
    enforce_origin(request)
    enforce_csrf(request, principal)


def require_workspace_permission(principal: Principal, membership, permission: Permission) -> None:
    try:
        require_permission(membership, permission)
    except IdentityError as error:
        raise to_api_error(error) from error
