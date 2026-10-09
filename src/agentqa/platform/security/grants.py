from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.values import SensitiveValue
from agentqa.platform.security.taint import SecurityError


class GrantPurpose(StrEnum):
    PROVIDER_AUTH_HEADER = "provider_auth_header"
    BROWSER_FILL = "browser_fill"


@dataclass(frozen=True)
class SecretGrant:
    id: UUID
    workspace_id: UUID
    credential_id: UUID
    credential_version: int
    principal: str
    purpose: GrantPurpose
    destination: str
    target_identity: str | None
    expires_at: datetime
    revoked_at: datetime | None = None
    run_id: UUID | None = None
    attempt_id: UUID | None = None


Resolver = Callable[["SecretGrant"], Awaitable[SensitiveValue]]


class GrantService:
    def __init__(self, *, resolver: Resolver, provider_origins: Mapping[ProviderRoute, str]) -> None:
        self._resolver = resolver
        self._provider_origins = dict(provider_origins)

    def _ensure_active(self, grant: SecretGrant, now: datetime) -> None:
        if grant.revoked_at is not None:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Grant đã bị thu hồi")
        if grant.expires_at <= now:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Grant đã hết hạn")

    async def authorize_provider_header(
        self, grant: SecretGrant, *, route: ProviderRoute, origin: str, now: datetime | None = None
    ) -> SensitiveValue:
        self._ensure_active(grant, now or datetime.now(UTC))
        if grant.purpose is not GrantPurpose.PROVIDER_AUTH_HEADER:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Grant không dành cho provider header")
        expected = self._provider_origins.get(route)
        if expected is None or origin != expected or grant.destination != expected:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Destination provider không khớp grant")
        return await self._resolve(grant)

    async def authorize_fill_target(
        self,
        grant: SecretGrant,
        *,
        target_identity: str,
        context_key: str,
        now: datetime | None = None,
    ) -> SensitiveValue:
        self._ensure_active(grant, now or datetime.now(UTC))
        if grant.purpose is not GrantPurpose.BROWSER_FILL:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Grant không dành cho browser fill")
        if target_identity != grant.destination:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Target identity không khớp grant")
        if not context_key or context_key != grant.target_identity:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Context không khớp grant")
        return await self._resolve(grant)

    async def _resolve(self, grant: SecretGrant) -> SensitiveValue:
        try:
            return await self._resolver(grant)
        except SecurityError:
            raise
        except Exception as error:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Không resolve được credential") from error
