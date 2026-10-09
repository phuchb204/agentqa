from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 5


def configure_event_loop_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_engine(
    dsn: str, *, pool_size: int = DEFAULT_POOL_SIZE, max_overflow: int = DEFAULT_MAX_OVERFLOW
) -> AsyncEngine:
    return create_async_engine(dsn, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def task_transaction(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        yield session
