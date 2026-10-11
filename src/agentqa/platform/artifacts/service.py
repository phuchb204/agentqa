from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.platform.artifacts.store import BlobStoreError, FileSystemBlobStore
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


@dataclass(frozen=True)
class ArtifactView:
    id: UUID
    workspace_id: UUID
    run_id: UUID | None
    kind: str
    state: str
    digest: str | None
    size_bytes: int | None
    media_type: str | None
    retention: str
    object_key: str | None
    unavailable_reason: str | None
    created_at: datetime
    available_at: datetime | None
    tombstoned_at: datetime | None


@dataclass(frozen=True)
class ReconcileReport:
    published: int
    unavailable: int
    scanned: int


def _view(row) -> ArtifactView:
    return ArtifactView(
        id=row.id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        kind=row.kind,
        state=row.state,
        digest=row.digest,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        retention=row.retention,
        object_key=row.object_key,
        unavailable_reason=row.unavailable_reason,
        created_at=row.created_at,
        available_at=row.available_at,
        tombstoned_at=row.tombstoned_at,
    )


class ArtifactService:
    def __init__(
        self,
        engine: AsyncEngine,
        store: FileSystemBlobStore,
        *,
        taint: TaintRegistry | None = None,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._store = store
        self._taint = taint

    @property
    def store(self) -> FileSystemBlobStore:
        return self._store

    def assert_safe_payload(self, payload: bytes) -> None:
        if self._taint is not None:
            self._taint.assert_clean(payload, "artifact.blob")

    async def stage(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        kind: str,
        media_type: str,
        payload: bytes,
        retention: str = "run",
        run_id: UUID | None = None,
        redacted: bool = True,
    ) -> ArtifactView:
        self.assert_safe_payload(payload)
        artifact_id = uuid4()
        object_key = f"{workspace_id}/{run_id or 'unassigned'}/{artifact_id}"
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.insert(tables.artifacts).values(
                    id=artifact_id,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    kind=kind,
                    state="staged",
                    media_type=media_type,
                    retention=retention,
                    redacted=redacted,
                    object_key=object_key,
                )
            )

            try:
                self._store.write(object_key, payload)
            except BlobStoreError:
                updated = (
                    await session.execute(
                        sa.update(tables.artifacts)
                        .where(tables.artifacts.c.id == artifact_id)
                        .values(state="unavailable", unavailable_reason="blob_write_failed")
                        .returning(tables.artifacts)
                    )
                ).one()
                return _view(updated)

            digest = digest_artifact_bytes(payload)
            updated = (
                await session.execute(
                    sa.update(tables.artifacts)
                    .where(tables.artifacts.c.id == artifact_id)
                    .values(
                        state="available",
                        digest=digest,
                        size_bytes=len(payload),
                        available_at=datetime.now(UTC),
                        unavailable_reason=None,
                    )
                    .returning(tables.artifacts)
                )
            ).one()
        return _view(updated)

    async def get_authorized(self, *, workspace_id: UUID, principal_id: UUID, artifact_id: UUID) -> ArtifactView:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.artifacts).where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.id == artifact_id,
                    )
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy artifact trong scope")
        return _view(row)

    async def open_bytes(self, *, workspace_id: UUID, principal_id: UUID, artifact_id: UUID) -> bytes:
        view = await self.get_authorized(workspace_id=workspace_id, principal_id=principal_id, artifact_id=artifact_id)
        if view.state != "available" or view.object_key is None:
            raise IdentityError(ErrorCode.EVIDENCE_MISSING, "Artifact không khả dụng")
        return self._store.read(view.object_key)

    async def mark_unavailable(
        self, *, workspace_id: UUID, principal_id: UUID, artifact_id: UUID, reason: str
    ) -> ArtifactView:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.update(tables.artifacts)
                    .where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.id == artifact_id,
                    )
                    .values(state="unavailable", unavailable_reason=reason)
                    .returning(tables.artifacts)
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy artifact trong scope")
        return _view(row)

    async def tombstone(
        self, *, workspace_id: UUID, principal_id: UUID, artifact_id: UUID, reason: str
    ) -> ArtifactView:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.update(tables.artifacts)
                    .where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.id == artifact_id,
                    )
                    .values(
                        state="deleted",
                        tombstoned_at=datetime.now(UTC),
                        unavailable_reason=reason,
                    )
                    .returning(tables.artifacts)
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy artifact trong scope")
        return _view(row)

    async def reconcile(self, *, workspace_id: UUID, principal_id: UUID) -> ReconcileReport:
        published = 0
        unavailable = 0
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.artifacts).where(
                        tables.artifacts.c.workspace_id == workspace_id,
                        tables.artifacts.c.state == "staged",
                    )
                )
            ).all()
            for row in rows:
                if row.object_key and self._store.exists(row.object_key):
                    payload = self._store.read(row.object_key)
                    digest = digest_artifact_bytes(payload)
                    await session.execute(
                        sa.update(tables.artifacts)
                        .where(tables.artifacts.c.id == row.id)
                        .values(
                            state="available",
                            digest=digest,
                            size_bytes=len(payload),
                            available_at=datetime.now(UTC),
                        )
                    )
                    published += 1
                else:
                    await session.execute(
                        sa.update(tables.artifacts)
                        .where(tables.artifacts.c.id == row.id)
                        .values(state="unavailable", unavailable_reason="staged_without_blob")
                    )
                    unavailable += 1
        return ReconcileReport(published=published, unavailable=unavailable, scanned=len(rows))
