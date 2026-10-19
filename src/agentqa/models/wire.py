from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from importlib import metadata
from typing import Any
from urllib.parse import urlsplit

from agentqa.contracts.canonical import canonicalize
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode
from agentqa.contracts.models import ModelCallOutcome, ProviderRoute, Usage
from agentqa.contracts.values import JsonValue, ensure_safe_json

GO_CHAT_PATH = "/chat/completions"
ZEN_SYSTEMONE_PATH = "/systemone"

MODEL_ROUTE_ORIGINS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_GO: "https://opencode.ai/zen/go/v1",
    ProviderRoute.OPENCODE_ZEN: "https://opencode.ai/zen/v1",
    ProviderRoute.COMMANDCODE_CHAT: "https://api.commandcode.ai/provider/v1",
    ProviderRoute.COMMANDCODE_SYSTEMONE: "https://api.commandcode.ai/provider/v1",
}

MODEL_ROUTE_PATHS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_GO: GO_CHAT_PATH,
    ProviderRoute.OPENCODE_ZEN: ZEN_SYSTEMONE_PATH,
    ProviderRoute.COMMANDCODE_CHAT: GO_CHAT_PATH,
    ProviderRoute.COMMANDCODE_SYSTEMONE: ZEN_SYSTEMONE_PATH,
}

GO_WIRE_VERSION = "opencode-go-chat/1"
ZEN_WIRE_VERSION = "opencode-zen-systemone/1"
COMMANDCODE_CHAT_WIRE_VERSION = "commandcode-chat/1"
COMMANDCODE_SYSTEMONE_WIRE_VERSION = "commandcode-systemone/1"

WIRE_VERSIONS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_GO: GO_WIRE_VERSION,
    ProviderRoute.OPENCODE_ZEN: ZEN_WIRE_VERSION,
    ProviderRoute.COMMANDCODE_CHAT: COMMANDCODE_CHAT_WIRE_VERSION,
    ProviderRoute.COMMANDCODE_SYSTEMONE: COMMANDCODE_SYSTEMONE_WIRE_VERSION,
}


class ModelTransportError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
        attempts: tuple[CallAttempt, ...] = (),
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.attempts = attempts
        super().__init__(message)


@dataclass(frozen=True)
class CallAttempt:
    attempt: int
    started_at: datetime
    ended_at: datetime
    outcome: ModelCallOutcome
    usage: Usage | None = None
    error_code: ErrorCode | None = None
    resolved_model: str | None = None


@dataclass(frozen=True)
class ImagePayload:
    media_type: str
    data: bytes


ImageLoader = Callable[[str], ImagePayload]


def route_origin(route: ProviderRoute) -> str:
    origin = MODEL_ROUTE_ORIGINS.get(route)
    if origin is None:
        raise ModelTransportError(ErrorCode.PERMISSION_DENIED, f"Route '{route}' không nằm trong danh sách cho phép")
    return origin


def ensure_route_origin(route: ProviderRoute, base_url: str) -> str:
    normalized = base_url.rstrip("/")
    expected = route_origin(route)
    if normalized != expected:
        raise ModelTransportError(
            ErrorCode.PERMISSION_DENIED,
            f"Destination '{normalized}' không khớp route '{route.value}' được pin",
        )
    return normalized


def ensured_url(route: ProviderRoute, base_url: str) -> str:
    return ensure_route_origin(route, base_url) + MODEL_ROUTE_PATHS[route]


def user_agent() -> str:
    try:
        version = metadata.version("agentqa")
    except metadata.PackageNotFoundError:
        version = "0.1.0"
    return f"AgentQA/{version}"


def authorization_header(secret: str) -> str:
    return f"Bearer {secret}"


def retry_after_seconds(headers: Any) -> float | None:
    raw = None
    if headers is not None:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    return value


def classify_http_status(status_code: int, *, headers: Any = None) -> ModelTransportError:
    if 300 <= status_code < 400:
        return ModelTransportError(ErrorCode.PERMISSION_DENIED, f"Provider redirect bị từ chối: {status_code}")
    if status_code in (401, 403):
        return ModelTransportError(ErrorCode.PROVIDER_AUTH, f"Provider từ chối xác thực: {status_code}")
    if status_code == 402:
        return ModelTransportError(ErrorCode.PROVIDER_QUOTA, f"Provider hết quota: {status_code}")
    if status_code == 429:
        return ModelTransportError(
            ErrorCode.PROVIDER_RATE_LIMIT,
            f"Provider giới hạn tần suất: {status_code}",
            retryable=True,
            retry_after=retry_after_seconds(headers),
        )
    if status_code >= 500:
        return ModelTransportError(ErrorCode.PROVIDER_TIMEOUT, f"Provider lỗi tạm thời: {status_code}", retryable=True)
    return ModelTransportError(ErrorCode.PROVIDER_SCHEMA, f"Provider trả lỗi không retry được: {status_code}")


def parse_json_object(text: str) -> dict[str, JsonValue]:
    def reject_constant(value: str) -> JsonValue:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, f"JSON chứa hằng số không an toàn: {value}")

    try:
        parsed = json.loads(text, parse_constant=reject_constant)
    except ModelTransportError:
        raise
    except (TypeError, ValueError) as error:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Output không phải JSON hợp lệ") from error
    if not isinstance(parsed, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Output JSON phải là một object")
    _ensure_safe(parsed)
    return parsed


def _ensure_safe(value: Any) -> None:
    try:
        ensure_safe_json(value)
    except AgentQAValidationError as error:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Output JSON chứa giá trị không an toàn") from error


def digest_payload(payload: Any) -> str:
    return sha256(canonicalize(payload)).hexdigest()


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""
