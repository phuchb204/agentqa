from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.sources import SegmentPrivacy, SourcePrivacyClass, SourceRevisionState
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.extraction.service import ExtractionError, ExtractionService, RunnerResult
from agentqa.platform.extraction.validation import UploadRejected, validate_upload
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.security.redaction import RedactionService
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


@dataclass(frozen=True)
class SourceEntityView:
    id: UUID
    logical_key: str


@dataclass(frozen=True)
class SourceRevisionView:
    revision_id: UUID
    source_id: UUID
    logical_key: str
    revision_no: int
    filename: str
    media_type: str
    size_bytes: int
    file_digest: str
    privacy_class: str
    state: str
    unextractable_reason: str | None
    created_at: datetime
    segment_count: int


@dataclass(frozen=True)
class SourceSegmentView:
    ordinal: int
    anchor: dict
    text: str
    text_digest: str
    privacy: str


@dataclass(frozen=True)
class UploadOutcome:
    revision: SourceRevisionView
    segments: list[SourceSegmentView]


def _text_digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class SourceService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        store: FileSystemBlobStore,
        extraction: ExtractionService,
        redaction: RedactionService,
        taint: TaintRegistry | None = None,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._store = store
        self._extraction = extraction
        self._redaction = redaction
        self._taint = taint

    async def create_source(self, *, workspace_id: UUID, principal_id: UUID, logical_key: str) -> SourceEntityView:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            existing = (
                await session.execute(
                    sa.select(tables.sources.c.id).where(
                        tables.sources.c.workspace_id == workspace_id,
                        tables.sources.c.logical_key == logical_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                raise IdentityError(ErrorCode.DUPLICATE_KEY, "Logical key đã tồn tại")
            source_id = (
                await session.execute(
                    sa.insert(tables.sources)
                    .values(workspace_id=workspace_id, logical_key=logical_key)
                    .returning(tables.sources.c.id)
                )
            ).scalar_one()
        return SourceEntityView(id=source_id, logical_key=logical_key)

    async def list_sources(self, *, workspace_id: UUID, principal_id: UUID) -> list[SourceEntityView]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.sources.c.id, tables.sources.c.logical_key)
                    .where(tables.sources.c.workspace_id == workspace_id)
                    .order_by(tables.sources.c.logical_key)
                )
            ).all()
        return [SourceEntityView(id=row.id, logical_key=row.logical_key) for row in rows]

    async def upload_revision(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        source_id: UUID,
        filename: str,
        media_type: str,
        payload: bytes,
    ) -> UploadOutcome:
        revision_id = uuid4()
        object_key = f"sources/{workspace_id}/{revision_id}"
        file_digest = sha256(payload).hexdigest()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            source = (
                await session.execute(
                    sa.select(tables.sources.c.logical_key).where(
                        tables.sources.c.workspace_id == workspace_id, tables.sources.c.id == source_id
                    )
                )
            ).one_or_none()
            if source is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy source trong scope")
            latest = (
                await session.execute(
                    sa.select(sa.func.max(tables.source_revisions.c.revision_no)).where(
                        tables.source_revisions.c.workspace_id == workspace_id,
                        tables.source_revisions.c.source_id == source_id,
                    )
                )
            ).scalar_one_or_none()
            revision_no = int(latest or 0) + 1
            await session.execute(
                sa.insert(tables.source_revisions).values(
                    id=revision_id,
                    workspace_id=workspace_id,
                    source_id=source_id,
                    revision_no=revision_no,
                    filename=filename,
                    media_type=media_type,
                    size_bytes=len(payload),
                    file_digest=file_digest,
                    privacy_class=SourcePrivacyClass.STANDARD.value,
                    state=SourceRevisionState.QUARANTINED.value,
                    object_key=object_key,
                )
            )
            await session.execute(
                sa.insert(tables.extraction_jobs).values(
                    workspace_id=workspace_id,
                    source_revision_id=revision_id,
                    state="queued",
                )
            )
            self._store.write(object_key, payload)
        return await self._process_revision(
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_id=source_id,
            revision_id=revision_id,
            payload=payload,
        )

    async def extract_pending(self, *, workspace_id: UUID, principal_id: UUID, source_id: UUID) -> UploadOutcome:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            row = (
                await session.execute(
                    sa.select(tables.source_revisions)
                    .where(
                        tables.source_revisions.c.workspace_id == workspace_id,
                        tables.source_revisions.c.source_id == source_id,
                    )
                    .order_by(tables.source_revisions.c.revision_no.desc())
                    .limit(1)
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy revision trong scope")
        if row.state in (SourceRevisionState.QUARANTINED.value, SourceRevisionState.VALIDATED.value):
            if row.object_key is None:
                raise IdentityError(ErrorCode.EVIDENCE_MISSING, "Revision thiếu file gốc")
            payload = self._store.read(row.object_key)
            return await self._process_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                source_id=source_id,
                revision_id=row.id,
                payload=payload,
            )
        view, segments = await self.get_revision(
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_id=source_id,
            revision_no=row.revision_no,
        )
        return UploadOutcome(revision=view, segments=segments)

    async def list_revisions(
        self, *, workspace_id: UUID, principal_id: UUID, source_id: UUID
    ) -> list[SourceRevisionView]:
        segment_count = (
            sa.select(sa.func.count())
            .select_from(tables.source_segments)
            .where(
                tables.source_segments.c.workspace_id == tables.source_revisions.c.workspace_id,
                tables.source_segments.c.source_revision_id == tables.source_revisions.c.id,
            )
            .correlate(tables.source_revisions)
            .scalar_subquery()
        )
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            source = (
                await session.execute(
                    sa.select(tables.sources.c.logical_key).where(
                        tables.sources.c.workspace_id == workspace_id, tables.sources.c.id == source_id
                    )
                )
            ).one_or_none()
            if source is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy source trong scope")
            rows = (
                await session.execute(
                    sa.select(tables.source_revisions, segment_count.label("segment_count"))
                    .where(
                        tables.source_revisions.c.workspace_id == workspace_id,
                        tables.source_revisions.c.source_id == source_id,
                    )
                    .order_by(tables.source_revisions.c.revision_no)
                )
            ).all()
        return [
            SourceRevisionView(
                revision_id=row.id,
                source_id=row.source_id,
                logical_key=source.logical_key,
                revision_no=row.revision_no,
                filename=row.filename,
                media_type=row.media_type,
                size_bytes=row.size_bytes,
                file_digest=row.file_digest,
                privacy_class=row.privacy_class,
                state=row.state,
                unextractable_reason=row.unextractable_reason,
                created_at=row.created_at,
                segment_count=row.segment_count,
            )
            for row in rows
        ]

    async def get_revision(
        self, *, workspace_id: UUID, principal_id: UUID, source_id: UUID, revision_no: int
    ) -> tuple[SourceRevisionView, list[SourceSegmentView]]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            source = (
                await session.execute(
                    sa.select(tables.sources.c.logical_key).where(
                        tables.sources.c.workspace_id == workspace_id, tables.sources.c.id == source_id
                    )
                )
            ).one_or_none()
            if source is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy source trong scope")
            row = (
                await session.execute(
                    sa.select(tables.source_revisions).where(
                        tables.source_revisions.c.workspace_id == workspace_id,
                        tables.source_revisions.c.source_id == source_id,
                        tables.source_revisions.c.revision_no == revision_no,
                    )
                )
            ).one_or_none()
            if row is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy revision trong scope")
            segment_rows = (
                await session.execute(
                    sa.select(tables.source_segments)
                    .where(
                        tables.source_segments.c.workspace_id == workspace_id,
                        tables.source_segments.c.source_revision_id == row.id,
                    )
                    .order_by(tables.source_segments.c.ordinal)
                )
            ).all()
        view = SourceRevisionView(
            revision_id=row.id,
            source_id=row.source_id,
            logical_key=source.logical_key,
            revision_no=row.revision_no,
            filename=row.filename,
            media_type=row.media_type,
            size_bytes=row.size_bytes,
            file_digest=row.file_digest,
            privacy_class=row.privacy_class,
            state=row.state,
            unextractable_reason=row.unextractable_reason,
            created_at=row.created_at,
            segment_count=len(segment_rows),
        )
        segments = [
            SourceSegmentView(
                ordinal=segment.ordinal,
                anchor=segment.anchor,
                text=segment.text,
                text_digest=segment.text_digest,
                privacy=segment.privacy,
            )
            for segment in segment_rows
        ]
        return view, segments

    async def _process_revision(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        source_id: UUID,
        revision_id: UUID,
        payload: bytes,
    ) -> UploadOutcome:
        filename = ""
        try:
            async with self._factory() as session, session.begin():
                await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
                row = (
                    await session.execute(
                        sa.select(tables.source_revisions).where(
                            tables.source_revisions.c.workspace_id == workspace_id,
                            tables.source_revisions.c.id == revision_id,
                        )
                    )
                ).one()
                filename = row.filename
                await session.execute(
                    sa.update(tables.extraction_jobs)
                    .where(
                        tables.extraction_jobs.c.workspace_id == workspace_id,
                        tables.extraction_jobs.c.source_revision_id == revision_id,
                    )
                    .values(state="running", started_at=datetime.now(UTC))
                )
            kind = validate_upload(filename=filename, payload=payload)
        except UploadRejected as rejection:
            await self._fail_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                revision_id=revision_id,
                state=SourceRevisionState.REJECTED,
                reason=rejection.reason,
                job_state="failed",
            )
            raise AgentQAValidationError(
                [field_error(("file",), ErrorCode.INPUT_INVALID, rejection.message)]
            ) from rejection
        try:
            result = self._extraction.run(kind=kind, payload=payload)
        except ExtractionError as error:
            await self._fail_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                revision_id=revision_id,
                state=SourceRevisionState.REJECTED,
                reason=error.reason,
                job_state="failed",
            )
            raise
        return await self._settle_revision(
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_id=source_id,
            revision_id=revision_id,
            result=result,
        )

    async def _settle_revision(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        source_id: UUID,
        revision_id: UUID,
        result: RunnerResult,
    ) -> UploadOutcome:
        if result.status == "rejected":
            reason = result.reason or "invalid_document"
            await self._fail_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                revision_id=revision_id,
                state=SourceRevisionState.REJECTED,
                reason=reason,
                job_state="failed",
            )
            raise AgentQAValidationError(
                [field_error(("file",), ErrorCode.INPUT_INVALID, "File không thể trích xuất an toàn")]
            )
        if result.status == "unextractable":
            reason = result.reason or "no_extractable_text"
            await self._fail_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                revision_id=revision_id,
                state=SourceRevisionState.UNEXTRACTABLE,
                reason=reason,
                job_state="unextractable",
            )
            view, segments = await self.get_revision(
                workspace_id=workspace_id,
                principal_id=principal_id,
                source_id=source_id,
                revision_no=await self._revision_no(
                    workspace_id=workspace_id, principal_id=principal_id, revision_id=revision_id
                ),
            )
            return UploadOutcome(revision=view, segments=segments)
        any_redacted = False
        safe_segments: list[tuple[dict, str, str]] = []
        for segment in result.segments:
            text = self._redaction.redact_text(segment.text)
            privacy = SegmentPrivacy.SAFE.value
            if text != segment.text:
                privacy = SegmentPrivacy.REDACTED.value
                any_redacted = True
            safe_segments.append((segment.anchor.model_dump(mode="json", exclude_none=True), text, privacy))
        if self._taint is not None:
            self._taint.assert_clean([text for _, text, _ in safe_segments], "source.segments")
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            for ordinal, (anchor, text, privacy) in enumerate(safe_segments):
                await session.execute(
                    sa.insert(tables.source_segments).values(
                        workspace_id=workspace_id,
                        source_revision_id=revision_id,
                        ordinal=ordinal,
                        anchor=anchor,
                        text=text,
                        text_digest=_text_digest(text),
                        privacy=privacy,
                    )
                )
            await session.execute(
                sa.update(tables.source_revisions)
                .where(
                    tables.source_revisions.c.workspace_id == workspace_id,
                    tables.source_revisions.c.id == revision_id,
                )
                .values(
                    state=SourceRevisionState.EXTRACTED.value,
                    privacy_class=(
                        SourcePrivacyClass.SENSITIVE.value if any_redacted else SourcePrivacyClass.STANDARD.value
                    ),
                    unextractable_reason=None,
                )
            )
            await session.execute(
                sa.update(tables.extraction_jobs)
                .where(
                    tables.extraction_jobs.c.workspace_id == workspace_id,
                    tables.extraction_jobs.c.source_revision_id == revision_id,
                )
                .values(state="succeeded", finished_at=datetime.now(UTC))
            )
        revision_no = await self._revision_no(
            workspace_id=workspace_id, principal_id=principal_id, revision_id=revision_id
        )
        view, segments = await self.get_revision(
            workspace_id=workspace_id,
            principal_id=principal_id,
            source_id=source_id,
            revision_no=revision_no,
        )
        return UploadOutcome(revision=view, segments=segments)

    async def _fail_revision(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        revision_id: UUID,
        state: SourceRevisionState,
        reason: str,
        job_state: str,
    ) -> None:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.update(tables.source_revisions)
                .where(
                    tables.source_revisions.c.workspace_id == workspace_id,
                    tables.source_revisions.c.id == revision_id,
                )
                .values(state=state.value, unextractable_reason=reason)
            )
            await session.execute(
                sa.update(tables.extraction_jobs)
                .where(
                    tables.extraction_jobs.c.workspace_id == workspace_id,
                    tables.extraction_jobs.c.source_revision_id == revision_id,
                )
                .values(state=job_state, reason=reason, finished_at=datetime.now(UTC))
            )

    async def _revision_no(self, *, workspace_id: UUID, principal_id: UUID, revision_id: UUID) -> int:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            return (
                await session.execute(
                    sa.select(tables.source_revisions.c.revision_no).where(
                        tables.source_revisions.c.workspace_id == workspace_id,
                        tables.source_revisions.c.id == revision_id,
                    )
                )
            ).scalar_one()
