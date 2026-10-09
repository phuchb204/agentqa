from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.identity.sessions import LoginResult, SessionService
from agentqa.platform.identity.tokens import generate_nonce
from agentqa.platform.security.origin import OriginPolicy, is_loopback_host
from agentqa.platform.security.taint import SecurityError

DEFAULT_BOOTSTRAP_TTL = timedelta(minutes=2)


@dataclass(frozen=True)
class BootstrapTicket:
    nonce: str
    expires_at: datetime


class LocalBootstrapService:
    def __init__(
        self,
        *,
        policy: OriginPolicy,
        sessions: SessionService,
        ttl: timedelta = DEFAULT_BOOTSTRAP_TTL,
    ) -> None:
        self._policy = policy
        self._sessions = sessions
        self._ttl = ttl
        self._tickets: dict[str, datetime] = {}

    @property
    def policy(self) -> OriginPolicy:
        return self._policy

    def issue_nonce(self) -> BootstrapTicket:
        if self._policy.profile != "local":
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Shared profile cấm local bootstrap")
        nonce = generate_nonce()
        expires_at = datetime.now(UTC) + self._ttl
        self._tickets[nonce] = expires_at
        return BootstrapTicket(nonce=nonce, expires_at=expires_at)

    async def exchange(
        self,
        *,
        nonce: str,
        origin: str | None,
        request_host: str | None,
        client_host: str | None,
        owner_user_id: UUID,
        owner_username: str,
    ) -> LoginResult:
        if self._policy.profile != "local":
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Shared profile cấm local bootstrap")
        if not is_loopback_host(client_host):
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Bootstrap chỉ nhận kết nối loopback")
        self._policy.check(origin, request_host=request_host)
        expires_at = self._tickets.pop(nonce, None)
        if expires_at is None:
            raise SecurityError(ErrorCode.PERMISSION_DENIED, "Nonce không hợp lệ hoặc đã dùng")
        if expires_at <= datetime.now(UTC):
            raise IdentityError(ErrorCode.PERMISSION_DENIED, "Nonce đã hết hạn")
        return await self._sessions.create_for_user(user_id=owner_user_id, username=owner_username)
