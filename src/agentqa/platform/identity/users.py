from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError, UserRecord
from agentqa.platform.identity.passwords import hash_password
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory


class UserService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def create(self, *, username: str, password: str, display_name: str | None = None) -> UserRecord:
        user_id = uuid4()
        async with self._factory() as session, session.begin():
            exists = (
                await session.execute(
                    sa.select(tables.users.c.id).where(sa.func.lower(tables.users.c.username) == username.lower())
                )
            ).one_or_none()
            if exists is not None:
                raise IdentityError(ErrorCode.DUPLICATE_KEY, "Username đã tồn tại")
            await session.execute(
                sa.insert(tables.users).values(
                    id=user_id,
                    username=username,
                    display_name=display_name or username,
                    password_hash=hash_password(password),
                )
            )
        return UserRecord(id=user_id, username=username, password_hash=None, status="active")

    async def find_by_username(self, username: str) -> UserRecord | None:
        async with self._factory() as session:
            row = (
                await session.execute(
                    sa.select(tables.users).where(sa.func.lower(tables.users.c.username) == username.lower())
                )
            ).one_or_none()
        return None if row is None else self._to_record(row)

    async def get(self, user_id: UUID) -> UserRecord | None:
        async with self._factory() as session:
            row = (await session.execute(sa.select(tables.users).where(tables.users.c.id == user_id))).one_or_none()
        return None if row is None else self._to_record(row)

    async def first_user(self) -> UserRecord | None:
        async with self._factory() as session:
            row = (
                await session.execute(
                    sa.select(tables.users).order_by(tables.users.c.created_at, tables.users.c.id).limit(1)
                )
            ).one_or_none()
        return None if row is None else self._to_record(row)

    def _to_record(self, row) -> UserRecord:
        return UserRecord(id=row.id, username=row.username, password_hash=row.password_hash, status=row.status)
