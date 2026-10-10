from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import yaml
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import CaseContent
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.revisions.content import CONTENT_MODELS
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

KINDS = ("case", "requirement", "environment", "suite", "dataset", "fixture")

ENTITY_TABLES: dict[str, tuple[Any, str, Any]] = {
    "case": (tables.cases, "case_id", tables.case_revisions),
    "requirement": (tables.requirements, "requirement_id", tables.requirement_revisions),
    "environment": (tables.applications, "application_id", tables.environment_revisions),
    "suite": (tables.suites, "suite_id", tables.suite_revisions),
    "dataset": (tables.datasets, "dataset_id", tables.dataset_revisions),
    "fixture": (tables.fixtures, "fixture_id", tables.fixture_revisions),
}

BUNDLE_VERSION = "revision-bundle/1"
FORBIDDEN_BUNDLE_KEYS = ("credentials", "credential_refs", "credential_grants", "confirmation", "confirmation_ref")


class RevisionConflict(IdentityError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INPUT_INVALID, message)
        self.status_code = 412


class RevisionPreconditionRequired(IdentityError):
    def __init__(self, message: str = "Thiếu If-Match cho draft") -> None:
        super().__init__(ErrorCode.INPUT_INVALID, message)
        self.status_code = 428


@dataclass(frozen=True)
class DraftState:
    entity_id: UUID
    edit_version: int
    content: dict
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True)
class RevisionView:
    revision_id: UUID
    entity_id: UUID
    revision_no: int
    content: dict
    content_digest: str
    lifecycle: str
    author: str
    promoted_by: str | None
    promoted_at: datetime | None
    supersedes: UUID | None
    archived_at: datetime | None


@dataclass(frozen=True)
class PromotionReceipt:
    revision_id: UUID
    entity_id: UUID
    revision_no: int
    content_digest: str
    promoted_by: str
    promoted_at: datetime
    supersedes: UUID | None


@dataclass(frozen=True)
class EntityView:
    id: UUID
    logical_key: str


def validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise IdentityError(ErrorCode.INPUT_INVALID, f"Kind '{kind}' không hỗ trợ")


def validate_content(kind: str, content: dict) -> None:
    if kind == "case":
        try:
            CaseContent.model_validate(content)
        except ValidationError as error:
            raise AgentQAValidationError(
                [
                    field_error(
                        ("content", *[str(part) for part in item.get("loc", ())]),
                        ErrorCode.INPUT_INVALID,
                        str(item.get("msg", "Dữ liệu không hợp lệ")),
                    )
                    for item in error.errors()
                ]
            ) from error
        compile_case_document(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))
        return
    model = CONTENT_MODELS.get(kind)
    if model is None:
        raise IdentityError(ErrorCode.INPUT_INVALID, f"Kind '{kind}' chưa có schema content")
    try:
        model.model_validate(content)
    except ValidationError as error:
        raise AgentQAValidationError(
            [
                field_error(
                    ("content", *[str(part) for part in item.get("loc", ())]),
                    ErrorCode.INPUT_INVALID,
                    str(item.get("msg", "Dữ liệu không hợp lệ")),
                )
                for item in error.errors()
            ]
        ) from error


class RevisionService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def create_entity(
        self, *, workspace_id: UUID, principal_id: UUID, kind: str, logical_key: str, name: str | None = None
    ) -> EntityView:
        validate_kind(kind)
        entity_table, _column, _revision_table = ENTITY_TABLES[kind]
        values: dict[str, Any] = {"workspace_id": workspace_id, "logical_key": logical_key}
        if kind == "environment":
            values = {
                "workspace_id": workspace_id,
                "slug": logical_key,
                "name": name or logical_key,
            }
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            existing = (
                await session.execute(
                    sa.select(entity_table.c.id).where(
                        entity_table.c.workspace_id == workspace_id,
                        (entity_table.c.logical_key if kind != "environment" else entity_table.c.slug) == logical_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                raise IdentityError(ErrorCode.DUPLICATE_KEY, "Logical key đã tồn tại")
            result = await session.execute(sa.insert(entity_table).values(**values).returning(entity_table.c.id))
            entity_id = result.scalar_one()
        return EntityView(id=entity_id, logical_key=logical_key)

    async def list_entities(
        self, *, workspace_id: UUID, principal_id: UUID, kind: str, logical_key: str | None = None, limit: int = 50
    ) -> list[EntityView]:
        validate_kind(kind)
        entity_table, _column, _revision_table = ENTITY_TABLES[kind]
        key_column = entity_table.c.logical_key if kind != "environment" else entity_table.c.slug
        statement = (
            sa.select(entity_table.c.id, key_column.label("key"))
            .where(entity_table.c.workspace_id == workspace_id)
            .order_by(key_column)
            .limit(min(limit, 200))
        )
        if logical_key is not None:
            statement = statement.where(key_column == logical_key)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (await session.execute(statement)).all()
        return [EntityView(id=row.id, logical_key=row.key) for row in rows]

    async def get_draft(self, *, workspace_id: UUID, principal_id: UUID, case_id: UUID) -> DraftState | None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.case_drafts).where(
                        tables.case_drafts.c.workspace_id == workspace_id,
                        tables.case_drafts.c.case_id == case_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return DraftState(
            entity_id=row.case_id,
            edit_version=row.edit_version,
            content=row.content,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    async def save_draft(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        case_id: UUID,
        content: dict,
        expected_edit_version: int | None,
    ) -> DraftState:
        if expected_edit_version is None:
            raise RevisionPreconditionRequired()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            entity = (
                await session.execute(
                    sa.select(tables.cases.c.id).where(
                        tables.cases.c.workspace_id == workspace_id, tables.cases.c.id == case_id
                    )
                )
            ).one_or_none()
            if entity is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy case trong scope")
            draft = (
                await session.execute(
                    sa.select(tables.case_drafts).where(
                        tables.case_drafts.c.workspace_id == workspace_id,
                        tables.case_drafts.c.case_id == case_id,
                    )
                )
            ).one_or_none()
            if draft is None:
                if expected_edit_version not in (0,):
                    raise RevisionConflict("Draft chưa tồn tại hoặc edit version không khớp")
                new_version = 1
                await session.execute(
                    sa.insert(tables.case_drafts).values(
                        workspace_id=workspace_id,
                        case_id=case_id,
                        edit_version=new_version,
                        content=content,
                        updated_by=actor,
                        updated_at=datetime.now(UTC),
                    )
                )
            else:
                if draft.edit_version != expected_edit_version:
                    raise RevisionConflict("Edit version đã thay đổi")
                new_version = draft.edit_version + 1
                await session.execute(
                    sa.update(tables.case_drafts)
                    .where(
                        tables.case_drafts.c.workspace_id == workspace_id,
                        tables.case_drafts.c.case_id == case_id,
                    )
                    .values(
                        edit_version=new_version,
                        content=content,
                        updated_by=actor,
                        updated_at=datetime.now(UTC),
                    )
                )
        return DraftState(
            entity_id=case_id,
            edit_version=new_version,
            content=content,
            updated_by=actor,
            updated_at=datetime.now(UTC),
        )

    async def promote_draft(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        case_id: UUID,
        expected_edit_version: int | None,
    ) -> PromotionReceipt:
        if expected_edit_version is None:
            raise RevisionPreconditionRequired()
        draft = await self.get_draft(workspace_id=workspace_id, principal_id=principal_id, case_id=case_id)
        if draft is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Chưa có draft để promote")
        if draft.edit_version != expected_edit_version:
            raise RevisionConflict("Edit version đã thay đổi")
        validate_content("case", draft.content)
        return await self._promote_content(
            workspace_id=workspace_id,
            principal_id=principal_id,
            actor=actor,
            kind="case",
            entity_id=case_id,
            content=draft.content,
        )

    async def promote_content(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        kind: str,
        entity_id: UUID,
        content: dict,
    ) -> PromotionReceipt:
        validate_content(kind, content)
        return await self._promote_content(
            workspace_id=workspace_id,
            principal_id=principal_id,
            actor=actor,
            kind=kind,
            entity_id=entity_id,
            content=content,
        )

    async def _promote_content(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        kind: str,
        entity_id: UUID,
        content: dict,
    ) -> PromotionReceipt:
        validate_kind(kind)
        entity_table, entity_column, revision_table = ENTITY_TABLES[kind]
        digest = digest_content(content)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            entity = (
                await session.execute(
                    sa.select(entity_table.c.id).where(
                        entity_table.c.workspace_id == workspace_id, entity_table.c.id == entity_id
                    )
                )
            ).one_or_none()
            if entity is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy entity trong scope")
            latest = (
                await session.execute(
                    sa.select(revision_table.c.revision_no, revision_table.c.id)
                    .where(
                        revision_table.c.workspace_id == workspace_id,
                        revision_table.c[entity_column] == entity_id,
                    )
                    .order_by(revision_table.c.revision_no.desc())
                    .limit(1)
                )
            ).one_or_none()
            revision_no = (latest[0] if latest else 0) + 1
            supersedes = latest[1] if latest else None
            now = datetime.now(UTC)
            revision_id = (
                await session.execute(
                    sa.insert(revision_table)
                    .values(
                        workspace_id=workspace_id,
                        **{entity_column: entity_id},
                        revision_no=revision_no,
                        content=content,
                        content_digest=digest,
                        lifecycle="ready",
                        author=actor,
                        promoted_by=actor,
                        promoted_at=now,
                        supersedes=supersedes,
                    )
                    .returning(revision_table.c.id)
                )
            ).scalar_one()
            if kind == "case":
                requirement_keys = [key for key in content.get("requirements", []) if isinstance(key, str)]
                if requirement_keys:
                    requirement_rows = (
                        await session.execute(
                            sa.select(tables.requirements.c.id).where(
                                tables.requirements.c.workspace_id == workspace_id,
                                tables.requirements.c.logical_key.in_(requirement_keys),
                            )
                        )
                    ).all()
                    source_names = sorted(str(key) for key in content.get("source_defs", {}))
                    for requirement_row in requirement_rows:
                        await session.execute(
                            sa.insert(tables.case_source_links).values(
                                workspace_id=workspace_id,
                                case_id=entity_id,
                                case_revision_id=revision_id,
                                requirement_id=requirement_row.id,
                                source_names=source_names,
                                needs_review=False,
                            )
                        )
            elif kind == "requirement":
                await session.execute(
                    sa.update(tables.case_source_links)
                    .where(
                        tables.case_source_links.c.workspace_id == workspace_id,
                        tables.case_source_links.c.requirement_id == entity_id,
                    )
                    .values(
                        needs_review=True,
                        marked_by_requirement_revision=revision_id,
                        review_marked_at=now,
                    )
                )
        return PromotionReceipt(
            revision_id=revision_id,
            entity_id=entity_id,
            revision_no=revision_no,
            content_digest=digest,
            promoted_by=actor,
            promoted_at=now,
            supersedes=supersedes,
        )

    async def list_revisions(
        self, *, workspace_id: UUID, principal_id: UUID, kind: str, entity_id: UUID
    ) -> list[RevisionView]:
        validate_kind(kind)
        entity_table, entity_column, revision_table = ENTITY_TABLES[kind]
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            entity = (
                await session.execute(
                    sa.select(entity_table.c.id).where(
                        entity_table.c.workspace_id == workspace_id, entity_table.c.id == entity_id
                    )
                )
            ).one_or_none()
            if entity is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy entity trong scope")
            rows = (
                await session.execute(
                    sa.select(revision_table)
                    .where(
                        revision_table.c.workspace_id == workspace_id,
                        revision_table.c[entity_column] == entity_id,
                    )
                    .order_by(revision_table.c.revision_no)
                )
            ).all()
        return [
            RevisionView(
                revision_id=row.id,
                entity_id=row._mapping[entity_column],
                revision_no=row.revision_no,
                content=row.content,
                content_digest=row.content_digest,
                lifecycle=row.lifecycle,
                author=row.author,
                promoted_by=row.promoted_by,
                promoted_at=row.promoted_at,
                supersedes=row.supersedes,
                archived_at=row.archived_at,
            )
            for row in rows
        ]

    async def get_revision(
        self, *, workspace_id: UUID, principal_id: UUID, kind: str, entity_id: UUID, revision_no: int
    ) -> RevisionView:
        revisions = await self.list_revisions(
            workspace_id=workspace_id, principal_id=principal_id, kind=kind, entity_id=entity_id
        )
        for revision in revisions:
            if revision.revision_no == revision_no:
                return revision
        raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy revision")

    async def archive_revision(
        self, *, workspace_id: UUID, principal_id: UUID, kind: str, revision_id: UUID
    ) -> RevisionView:
        validate_kind(kind)
        _entity_table, _entity_column, revision_table = ENTITY_TABLES[kind]
        now = datetime.now(UTC)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            result = await session.execute(
                sa.update(revision_table)
                .where(
                    revision_table.c.workspace_id == workspace_id,
                    revision_table.c.id == revision_id,
                )
                .values(lifecycle="archived", archived_at=now)
                .returning(revision_table)
            )
            row = result.one_or_none()
            if row is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy revision trong scope")
            entity_column = ENTITY_TABLES[kind][1]
            view = RevisionView(
                revision_id=row.id,
                entity_id=row._mapping[entity_column],
                revision_no=row.revision_no,
                content=row.content,
                content_digest=row.content_digest,
                lifecycle=row.lifecycle,
                author=row.author,
                promoted_by=row.promoted_by,
                promoted_at=row.promoted_at,
                supersedes=row.supersedes,
                archived_at=row.archived_at,
            )
        return view

    async def export_bundle(self, *, workspace_id: UUID, principal_id: UUID, kind: str) -> dict:
        validate_kind(kind)
        entity_table, entity_column, revision_table = ENTITY_TABLES[kind]
        key_column = entity_table.c.logical_key if kind != "environment" else entity_table.c.slug
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(
                        key_column.label("logical_key"),
                        revision_table.c.revision_no,
                        revision_table.c.content,
                        revision_table.c.content_digest,
                        revision_table.c.lifecycle,
                        revision_table.c.archived_at,
                    )
                    .join(
                        entity_table,
                        (entity_table.c.id == revision_table.c[entity_column])
                        & (entity_table.c.workspace_id == revision_table.c.workspace_id),
                    )
                    .where(revision_table.c.workspace_id == workspace_id)
                    .order_by(key_column, revision_table.c.revision_no)
                )
            ).all()
        return {
            "schema_version": BUNDLE_VERSION,
            "kind": kind,
            "revisions": [
                {
                    "logical_key": row.logical_key,
                    "revision_no": row.revision_no,
                    "content": row.content,
                    "content_digest": row.content_digest,
                    "lifecycle": row.lifecycle,
                    "archived_at": row.archived_at.isoformat() if row.archived_at else None,
                }
                for row in rows
            ],
        }

    async def import_bundle(
        self, *, workspace_id: UUID, principal_id: UUID, actor: str, bundle: dict
    ) -> list[PromotionReceipt]:
        if bundle.get("schema_version") != BUNDLE_VERSION:
            raise IdentityError(ErrorCode.UNSUPPORTED_SCHEMA_VERSION, "Bundle version không hỗ trợ")
        kind = bundle.get("kind")
        validate_kind(kind)
        receipts: list[PromotionReceipt] = []
        for item in bundle.get("revisions", []):
            forbidden = [key for key in FORBIDDEN_BUNDLE_KEYS if key in item]
            if forbidden:
                raise IdentityError(
                    ErrorCode.PERMISSION_DENIED,
                    f"Bundle chứa trường quyền/credential không được import: {', '.join(forbidden)}",
                )
            content = item.get("content")
            if not isinstance(content, dict):
                raise IdentityError(ErrorCode.INPUT_INVALID, "Revision content phải là object")
            expected = item.get("content_digest")
            if expected and digest_content(content) != expected:
                raise IdentityError(ErrorCode.INPUT_INVALID, "Content digest không khớp")
            validate_content(kind, content)
            key = item.get("logical_key")
            entities = await self.list_entities(
                workspace_id=workspace_id, principal_id=principal_id, kind=kind, logical_key=key
            )
            if entities:
                entity_id = entities[0].id
            else:
                entity_id = (
                    await self.create_entity(
                        workspace_id=workspace_id, principal_id=principal_id, kind=kind, logical_key=key
                    )
                ).id
            receipts.append(
                await self._promote_content(
                    workspace_id=workspace_id,
                    principal_id=principal_id,
                    actor=actor,
                    kind=kind,
                    entity_id=entity_id,
                    content=content,
                )
            )
        return receipts
