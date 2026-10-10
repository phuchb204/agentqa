from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError, Principal, TokenRecord
from agentqa.platform.identity.passwords import verify_password
from agentqa.platform.identity.tokens import generate_token, hash_token
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory

DEFAULT_SESSION_TTL = timedelta(hours=12)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LoginResult:
    raw_token: str
    csrf_token: str
    session_id: UUID
    user_id: UUID
    username: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    raw_token: str
    record: TokenRecord


class SessionService:
    def __init__(self, engine: AsyncEngine, *, ttl: timedelta = DEFAULT_SESSION_TTL) -> None:
        self._engine = engine
        self._factory = create_session_factory(engine)
        self._ttl = ttl

    async def login(self, *, username: str, password: str) -> LoginResult:
        async with self._factory() as session, session.begin():
            row = (
                await session.execute(
                    sa.select(tables.users).where(sa.func.lower(tables.users.c.username) == username.lower())
                )
            ).one_or_none()
            if row is None or row.status != "active" or not verify_password(password, row.password_hash):
                raise IdentityError(ErrorCode.PROVIDER_AUTH, "Thông tin đăng nhập không hợp lệ")
            return await self._create_session(session, user_id=row.id, username=row.username)

    async def create_for_user(self, *, user_id: UUID, username: str) -> LoginResult:
        async with self._factory() as session, session.begin():
            return await self._create_session(session, user_id=user_id, username=username)

    async def _create_session(self, session, *, user_id: UUID, username: str) -> LoginResult:
        raw_token = generate_token()
        csrf_token = generate_token()
        session_id = uuid4()
        expires_at = _now() + self._ttl
        await session.execute(
            sa.insert(tables.sessions).values(
                id=session_id,
                user_id=user_id,
                token_hash=hash_token(raw_token),
                csrf_hash=hash_token(csrf_token),
                expires_at=expires_at,
            )
        )
        return LoginResult(
            raw_token=raw_token,
            csrf_token=csrf_token,
            session_id=session_id,
            user_id=user_id,
            username=username,
            expires_at=expires_at,
        )

    async def authenticate(self, raw_token: str) -> Principal:
        async with self._factory() as session:
            row = (
                await session.execute(
                    sa.select(
                        tables.sessions.c.id,
                        tables.sessions.c.user_id,
                        tables.sessions.c.csrf_hash,
                        tables.sessions.c.expires_at,
                        tables.sessions.c.revoked_at,
                        tables.users.c.username,
                    )
                    .join(tables.users, tables.users.c.id == tables.sessions.c.user_id)
                    .where(tables.sessions.c.token_hash == hash_token(raw_token))
                )
            ).one_or_none()
        if row is None or row.revoked_at is not None or row.expires_at <= _now():
            raise IdentityError(ErrorCode.PERMISSION_DENIED, "Session không hợp lệ hoặc đã hết hạn")
        return Principal(user_id=row.user_id, username=row.username, session_id=row.id, csrf_hash=row.csrf_hash)

    async def rotate(self, raw_token: str) -> LoginResult:
        principal = await self.authenticate(raw_token)
        async with self._factory() as session, session.begin():
            await session.execute(
                sa.update(tables.sessions)
                .where(tables.sessions.c.id == principal.session_id, tables.sessions.c.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
            return await self._create_session(session, user_id=principal.user_id, username=principal.username)

    async def refresh_csrf(self, raw_token: str) -> str:
        principal = await self.authenticate(raw_token)
        csrf_token = generate_token()
        async with self._factory() as session, session.begin():
            await session.execute(
                sa.update(tables.sessions)
                .where(tables.sessions.c.id == principal.session_id, tables.sessions.c.revoked_at.is_(None))
                .values(csrf_hash=hash_token(csrf_token))
            )
        return csrf_token

    async def logout(self, raw_token: str) -> None:
        async with self._factory() as session, session.begin():
            await session.execute(
                sa.update(tables.sessions)
                .where(tables.sessions.c.token_hash == hash_token(raw_token), tables.sessions.c.revoked_at.is_(None))
                .values(revoked_at=_now())
            )


class TokenService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._factory = create_session_factory(engine)

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        scopes: tuple[str, ...] = (),
        permission_flags: tuple[str, ...] = (),
        expires_at: datetime | None = None,
    ) -> IssuedToken:
        raw_token = generate_token()
        token_id = uuid4()
        async with self._factory() as session, session.begin():
            await session.execute(
                sa.insert(tables.api_tokens).values(
                    id=token_id,
                    user_id=user_id,
                    name=name,
                    token_hash=hash_token(raw_token),
                    scopes=list(scopes),
                    permission_flags=list(permission_flags),
                    expires_at=expires_at,
                )
            )
        record = TokenRecord(
            id=token_id,
            user_id=user_id,
            token_hash=hash_token(raw_token),
            scopes=scopes,
            permission_flags=permission_flags,
            expires_at=expires_at,
            revoked_at=None,
        )
        return IssuedToken(raw_token=raw_token, record=record)

    async def authenticate(self, raw_token: str) -> Principal:
        async with self._factory() as session:
            row = (
                await session.execute(
                    sa.select(tables.api_tokens, tables.users.c.username)
                    .join(tables.users, tables.users.c.id == tables.api_tokens.c.user_id)
                    .where(tables.api_tokens.c.token_hash == hash_token(raw_token))
                )
            ).one_or_none()
        if row is None or row.revoked_at is not None:
            raise IdentityError(ErrorCode.PERMISSION_DENIED, "Token không hợp lệ")
        if row.expires_at is not None and row.expires_at <= _now():
            raise IdentityError(ErrorCode.PERMISSION_DENIED, "Token đã hết hạn")
        return Principal(
            user_id=row.user_id,
            username=row.username,
            token_id=row.id,
            scopes=tuple(row.scopes or ()),
        )

    async def revoke(self, *, token_id: UUID, user_id: UUID, reason: str | None = None) -> None:
        async with self._factory() as session, session.begin():
            result = await session.execute(
                sa.update(tables.api_tokens)
                .where(
                    tables.api_tokens.c.id == token_id,
                    tables.api_tokens.c.user_id == user_id,
                    tables.api_tokens.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now(), revoke_reason=reason)
            )
            if result.rowcount == 0:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy token")

    async def list_for_user(self, user_id: UUID) -> list[TokenRecord]:
        async with self._factory() as session:
            rows = (
                await session.execute(sa.select(tables.api_tokens).where(tables.api_tokens.c.user_id == user_id))
            ).all()
        return [
            TokenRecord(
                id=row.id,
                user_id=row.user_id,
                token_hash=row.token_hash,
                scopes=tuple(row.scopes or ()),
                permission_flags=tuple(row.permission_flags or ()),
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
