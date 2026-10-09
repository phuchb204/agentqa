from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import (
    IdentityError,
    MembershipRecord,
    Permission,
    Role,
    require_permission,
)
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_principal, set_scope


@dataclass(frozen=True)
class WorkspaceRecord:
    id: UUID
    slug: str
    name: str


class PermissionCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[UUID, UUID], MembershipRecord] = {}

    def get(self, workspace_id: UUID, user_id: UUID) -> MembershipRecord | None:
        return self._entries.get((workspace_id, user_id))

    def put(self, record: MembershipRecord) -> None:
        self._entries[(record.workspace_id, record.user_id)] = record

    def invalidate_workspace(self, workspace_id: UUID) -> None:
        for key in [key for key in self._entries if key[0] == workspace_id]:
            del self._entries[key]

    def invalidate_user(self, workspace_id: UUID, user_id: UUID) -> None:
        self._entries.pop((workspace_id, user_id), None)


class AuthorizationService:
    def __init__(self, engine: AsyncEngine, *, cache: PermissionCache | None = None) -> None:
        self._factory = create_session_factory(engine)
        self._cache = cache or PermissionCache()

    @property
    def cache(self) -> PermissionCache:
        return self._cache

    async def membership(self, *, workspace_id: UUID, user_id: UUID) -> MembershipRecord | None:
        cached = self._cache.get(workspace_id, user_id)
        if cached is not None:
            return cached
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(
                        tables.memberships.c.workspace_id,
                        tables.memberships.c.user_id,
                        tables.memberships.c.role,
                        tables.memberships.c.permission_flags,
                    ).where(
                        tables.memberships.c.workspace_id == workspace_id,
                        tables.memberships.c.user_id == user_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        record = MembershipRecord(
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            role=Role(row.role),
            permission_flags=tuple(row.permission_flags or ()),
        )
        self._cache.put(record)
        return record

    async def require(self, *, workspace_id: UUID, user_id: UUID, permission: Permission) -> MembershipRecord:
        record = await self.membership(workspace_id=workspace_id, user_id=user_id)
        return require_permission(record, permission)

    async def create_workspace(self, *, actor_id: UUID, slug: str, name: str) -> WorkspaceRecord:
        workspace_id = uuid4()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=actor_id, workspace_id=workspace_id)
            await session.execute(sa.insert(tables.workspaces).values(id=workspace_id, slug=slug, name=name))
            await session.execute(
                sa.insert(tables.memberships).values(workspace_id=workspace_id, user_id=actor_id, role=Role.OWNER.value)
            )
        return WorkspaceRecord(id=workspace_id, slug=slug, name=name)

    async def list_workspaces(self, *, user_id: UUID) -> list[WorkspaceRecord]:
        async with self._factory() as session, session.begin():
            await set_principal(session, principal_id=user_id)
            rows = (
                await session.execute(
                    sa.select(tables.memberships.c.workspace_id).where(tables.memberships.c.user_id == user_id)
                )
            ).all()
            records: list[WorkspaceRecord] = []
            for row in rows:
                await set_scope(session, principal_id=user_id, workspace_id=row.workspace_id)
                workspace = (
                    await session.execute(
                        sa.select(tables.workspaces).where(tables.workspaces.c.id == row.workspace_id)
                    )
                ).one_or_none()
                if workspace is not None:
                    records.append(WorkspaceRecord(id=workspace.id, slug=workspace.slug, name=workspace.name))
        return records

    async def list_memberships(self, *, workspace_id: UUID, user_id: UUID) -> list[MembershipRecord]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(
                        tables.memberships.c.workspace_id,
                        tables.memberships.c.user_id,
                        tables.memberships.c.role,
                        tables.memberships.c.permission_flags,
                    ).where(tables.memberships.c.workspace_id == workspace_id)
                )
            ).all()
        return [
            MembershipRecord(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                role=Role(row.role),
                permission_flags=tuple(row.permission_flags or ()),
            )
            for row in rows
        ]

    async def rename_workspace(self, *, workspace_id: UUID, user_id: UUID, name: str) -> WorkspaceRecord:
        await self.require(workspace_id=workspace_id, user_id=user_id, permission=Permission.WORKSPACE_MANAGE)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=user_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.update(tables.workspaces)
                    .where(tables.workspaces.c.id == workspace_id)
                    .values(name=name)
                    .returning(tables.workspaces.c.id, tables.workspaces.c.slug, tables.workspaces.c.name)
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy workspace trong scope")
        return WorkspaceRecord(id=row.id, slug=row.slug, name=row.name)

    async def add_membership(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        role: Role,
        permission_flags: tuple[str, ...] = (),
    ) -> MembershipRecord:
        await self.require(workspace_id=workspace_id, user_id=actor_id, permission=Permission.MEMBERSHIP_MANAGE)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=actor_id, workspace_id=workspace_id)
            await session.execute(
                sa.insert(tables.memberships).values(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=role.value,
                    permission_flags=list(permission_flags),
                )
            )
        self._cache.invalidate_workspace(workspace_id)
        return MembershipRecord(
            workspace_id=workspace_id, user_id=user_id, role=role, permission_flags=permission_flags
        )

    async def change_role(self, *, workspace_id: UUID, actor_id: UUID, user_id: UUID, role: Role) -> MembershipRecord:
        await self.require(workspace_id=workspace_id, user_id=actor_id, permission=Permission.MEMBERSHIP_MANAGE)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=actor_id, workspace_id=workspace_id)
            if role is not Role.OWNER:
                await self._ensure_other_owner(session, workspace_id=workspace_id, user_id=user_id)
            result = await session.execute(
                sa.update(tables.memberships)
                .where(
                    tables.memberships.c.workspace_id == workspace_id,
                    tables.memberships.c.user_id == user_id,
                )
                .values(role=role.value, updated_at=datetime.now(UTC))
            )
            if result.rowcount == 0:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy membership")
        self._cache.invalidate_workspace(workspace_id)
        return MembershipRecord(workspace_id=workspace_id, user_id=user_id, role=role)

    async def remove_membership(self, *, workspace_id: UUID, actor_id: UUID, user_id: UUID) -> None:
        await self.require(workspace_id=workspace_id, user_id=actor_id, permission=Permission.MEMBERSHIP_MANAGE)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=actor_id, workspace_id=workspace_id)
            await self._ensure_other_owner(session, workspace_id=workspace_id, user_id=user_id)
            result = await session.execute(
                sa.delete(tables.memberships).where(
                    tables.memberships.c.workspace_id == workspace_id,
                    tables.memberships.c.user_id == user_id,
                )
            )
            if result.rowcount == 0:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy membership")
        self._cache.invalidate_workspace(workspace_id)

    async def _ensure_other_owner(self, session, *, workspace_id: UUID, user_id: UUID) -> None:
        target = (
            await session.execute(
                sa.select(tables.memberships.c.role).where(
                    tables.memberships.c.workspace_id == workspace_id,
                    tables.memberships.c.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if target != Role.OWNER.value:
            return
        owners = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(tables.memberships)
                .where(
                    tables.memberships.c.workspace_id == workspace_id,
                    tables.memberships.c.role == Role.OWNER.value,
                    tables.memberships.c.user_id != user_id,
                )
            )
        ).scalar_one()
        if owners == 0:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Workspace phải còn owner cuối")
