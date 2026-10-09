from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from agentqa.platform.storage import tables


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, slug: str, name: str) -> UUID:
        result = await self._session.execute(
            sa.insert(tables.workspaces).values(slug=slug, name=name).returning(tables.workspaces.c.id)
        )
        return result.scalar_one()

    async def add_member(
        self, *, workspace_id: UUID, user_id: UUID, role: str, permission_flags: tuple[str, ...] = ()
    ) -> UUID:
        result = await self._session.execute(
            sa.insert(tables.memberships)
            .values(
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
                permission_flags=list(permission_flags),
            )
            .returning(tables.memberships.c.id)
        )
        return result.scalar_one()

    async def role_of(self, *, workspace_id: UUID, user_id: UUID) -> str | None:
        result = await self._session.execute(
            sa.select(tables.memberships.c.role).where(
                tables.memberships.c.workspace_id == workspace_id,
                tables.memberships.c.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


class RevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_ready(
        self,
        table: sa.Table,
        *,
        workspace_id: UUID,
        entity_column: str,
        entity_id: UUID,
        revision_no: int,
        content: dict,
        content_digest: str,
        author: str,
        promoted_by: str | None = None,
    ) -> UUID:
        result = await self._session.execute(
            sa.insert(table)
            .values(
                workspace_id=workspace_id,
                **{entity_column: entity_id},
                revision_no=revision_no,
                content=content,
                content_digest=content_digest,
                lifecycle="ready",
                author=author,
                promoted_by=promoted_by,
                promoted_at=sa.func.now(),
            )
            .returning(table.c.id)
        )
        return result.scalar_one()

    async def archive(self, table: sa.Table, *, revision_id: UUID) -> None:
        await self._session.execute(
            sa.update(table).where(table.c.id == revision_id).values(lifecycle="archived", archived_at=sa.func.now())
        )


class SequenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate_run_seq(self, run_id: UUID) -> int:
        result = await self._session.execute(
            sa.update(tables.runs)
            .where(tables.runs.c.id == run_id)
            .values(next_run_seq=tables.runs.c.next_run_seq + 1)
            .returning(tables.runs.c.next_run_seq)
        )
        return result.scalar_one()

    async def allocate_execution_seq(self, execution_id: UUID) -> int:
        result = await self._session.execute(
            sa.update(tables.executions)
            .where(tables.executions.c.id == execution_id)
            .values(next_execution_seq=tables.executions.c.next_execution_seq + 1)
            .returning(tables.executions.c.next_execution_seq)
        )
        return result.scalar_one()
