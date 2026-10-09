from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from agentqa.contracts.errors import ErrorCode


class Role(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    RUNNER = "runner"
    VIEWER = "viewer"


class PermissionFlag(StrEnum):
    ARTIFACT_EXPORT = "artifact_export"
    RESEARCH_TRUTH_ACCESS = "research_truth_access"


class Permission(StrEnum):
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_MANAGE = "workspace.manage"
    MEMBERSHIP_MANAGE = "membership.manage"
    CASE_EDIT = "case.edit"
    CASE_PROMOTE = "case.promote"
    RUN_SUBMIT = "run.submit"
    RUN_CONTROL = "run.control"
    ARTIFACT_READ = "artifact.read"
    SETTINGS_MANAGE = "settings.manage"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.EDITOR: frozenset(
        {
            Permission.WORKSPACE_READ,
            Permission.CASE_EDIT,
            Permission.CASE_PROMOTE,
            Permission.RUN_SUBMIT,
            Permission.RUN_CONTROL,
            Permission.ARTIFACT_READ,
        }
    ),
    Role.RUNNER: frozenset(
        {
            Permission.WORKSPACE_READ,
            Permission.RUN_SUBMIT,
            Permission.RUN_CONTROL,
            Permission.ARTIFACT_READ,
        }
    ),
    Role.VIEWER: frozenset({Permission.WORKSPACE_READ, Permission.ARTIFACT_READ}),
}


class IdentityError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    username: str
    password_hash: str | None
    status: str


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    token_hash: str
    csrf_hash: str | None
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class TokenRecord:
    id: UUID
    user_id: UUID
    token_hash: str
    scopes: tuple[str, ...]
    permission_flags: tuple[str, ...]
    expires_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class MembershipRecord:
    workspace_id: UUID
    user_id: UUID
    role: Role
    permission_flags: tuple[str, ...] = field(default_factory=tuple)

    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    username: str
    session_id: UUID | None = None
    csrf_hash: str | None = None
    token_id: UUID | None = None
    scopes: tuple[str, ...] = ()


def permissions_for(membership: MembershipRecord) -> frozenset[Permission]:
    base = set(ROLE_PERMISSIONS[membership.role])
    if PermissionFlag.ARTIFACT_EXPORT in membership.permission_flags:
        base.add(Permission.ARTIFACT_READ)
    return frozenset(base)


def require_permission(membership: MembershipRecord | None, permission: Permission) -> MembershipRecord:
    if membership is None:
        raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy workspace trong scope")
    if permission not in permissions_for(membership):
        raise IdentityError(ErrorCode.PERMISSION_DENIED, "Không đủ quyền cho thao tác này")
    return membership
