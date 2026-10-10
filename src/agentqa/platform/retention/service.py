from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

DEFAULT_TTLS_DAYS: dict[str, int] = {"run": 7, "workspace": 30, "research": 365}


@dataclass(frozen=True)
class RetentionReport:
    expired: int = 0
    bytes_swept: int = 0
    orphans: list[str] = field(default_factory=list)
    failed_writes: int = 0


class RetentionService:
    def __init__(
        self,
        engine: AsyncEngine,
        store: FileSystemBlobStore,
        *,
        ttls_days: Mapping[str, int] | None = None,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._store = store
        self._ttls = dict(ttls_days or DEFAULT_TTLS_DAYS)

    async def expire_due(self, *, workspace_id: UUID, principal_id: UUID, now: datetime | None = None) -> int:
        moment = now or datetime.now(UTC)
        expired = 0
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            for retention_class, ttl_days in self._ttls.items():
                cutoff = moment - timedelta(days=ttl_days)
                result = await session.execute(
                    sa.update(tables.artifacts)
                    .where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.state == "available",
                        tables.artifacts.c.retention == retention_class,
                        tables.artifacts.c.created_at < cutoff,
                    )
                    .values(
                        state="deleted",
                        tombstoned_at=moment,
                        unavailable_reason=f"retention_expired:{retention_class}",
                    )
                )
                expired += int(result.rowcount or 0)
        return expired

    async def sweep_tombstones(self, *, workspace_id: UUID, principal_id: UUID) -> int:
        swept = 0
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.artifacts.c.id, tables.artifacts.c.object_key).where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.state == "deleted",
                        tables.artifacts.c.object_key.is_not(None),
                    )
                )
            ).all()
            for row in rows:
                if row.object_key and self._store.exists(row.object_key):
                    self._store.delete(row.object_key)
                    swept += 1
                await session.execute(
                    sa.update(tables.artifacts).where(tables.artifacts.c.id == row.id).values(object_key=None)
                )
        return swept

    async def scan_orphans(self, *, workspace_id: UUID, principal_id: UUID) -> list[str]:
        prefix = f"{workspace_id}/"
        root = self._store.root
        files: set[str] = set()
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    files.add(path.relative_to(root).as_posix())
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.artifacts.c.object_key).where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.object_key.is_not(None),
                    )
                )
            ).all()
        known = {row.object_key for row in rows if row.object_key}
        return sorted(path for path in files if path.startswith(prefix) and path not in known)

    async def count_failed_writes(self, *, workspace_id: UUID, principal_id: UUID) -> int:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            count = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(tables.artifacts)
                    .where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.state == "unavailable",
                    )
                )
            ).scalar_one()
        return int(count)
