from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hmac import compare_digest
from urllib.parse import urlsplit

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.tokens import hash_token
from agentqa.platform.security.taint import SecurityError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    cleaned = host.strip().strip("[]").split("%", 1)[0].lower()
    return cleaned in LOOPBACK_HOSTS or cleaned.startswith("127.")


def _split_origin(origin: str) -> tuple[str, str, int | None]:
    parts = urlsplit(origin)
    if not parts.scheme or not parts.hostname:
        raise SecurityError(ErrorCode.INPUT_INVALID, "Origin không hợp lệ")
    port = parts.port
    return parts.scheme.lower(), parts.hostname.lower(), port


def _normalized_host_port(host: str, scheme: str) -> tuple[str, int]:
    if ":" in host:
        hostname, _, port_text = host.rpartition(":")
        port = int(port_text)
    else:
        hostname, port = host, (443 if scheme == "https" else 80)
    return hostname.strip().strip("[]").lower(), port


@dataclass(frozen=True)
class OriginPolicy:
    profile: str = "local"
    allowed_origins: frozenset[str] = frozenset()

    @classmethod
    def local(cls) -> OriginPolicy:
        return cls(profile="local", allowed_origins=frozenset())

    @classmethod
    def shared(cls, allowed_origins: Iterable[str]) -> OriginPolicy:
        origins = frozenset(origin.rstrip("/").lower() for origin in allowed_origins)
        if not origins:
            raise SecurityError(ErrorCode.INPUT_INVALID, "Shared profile cần allowlist Origin")
        return cls(profile="shared", allowed_origins=origins)

    @property
    def secure_cookies(self) -> bool:
        return self.profile == "shared"

    def check(self, origin: str | None, *, request_host: str | None) -> None:
        if not origin:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Thiếu Origin header")
        scheme, host, port = _split_origin(origin)
        normalized = origin.rstrip("/").lower()
        if self.profile == "shared":
            if normalized not in self.allowed_origins:
                raise SecurityError(ErrorCode.PERMISSION_DENIED, "Origin không nằm trong allowlist")
            if scheme != "https":
                raise SecurityError(ErrorCode.PERMISSION_DENIED, "Shared profile yêu cầu HTTPS")
            return
        if not is_loopback_host(host):
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Local profile chỉ chấp nhận Origin loopback")
        if scheme not in ("http", "https"):
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Scheme không hợp lệ")
        if request_host:
            request_hostname, request_port = _normalized_host_port(request_host, scheme)
            if request_hostname != host:
                raise SecurityError(ErrorCode.PERMISSION_DENIED, "Origin không cùng host với request")
            expected_port = port if port is not None else (443 if scheme == "https" else 80)
            if request_port != expected_port:
                raise SecurityError(ErrorCode.PERMISSION_DENIED, "Origin không cùng port với request")
        if port is not None and port <= 0:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Port không hợp lệ")


def issue_csrf_token(issue_token) -> tuple[str, str]:
    raw = issue_token()
    return raw, hash_token(raw)


def verify_csrf(stored_hash: str | None, provided: str | None) -> None:
    if not provided or not stored_hash or not compare_digest(stored_hash, hash_token(provided)):
        raise SecurityError(ErrorCode.PERMISSION_DENIED, "CSRF token không hợp lệ")
