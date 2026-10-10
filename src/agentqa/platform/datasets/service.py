from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


@dataclass(frozen=True)
class DatasetRowView:
    index: int
    parameters: dict
    row_digest: str


class DatasetService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def rows(self, *, workspace_id: UUID, principal_id: UUID, dataset_revision_id: UUID) -> list[DatasetRowView]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            revision = (
                await session.execute(
                    sa.select(tables.dataset_revisions.c.content).where(
                        tables.dataset_revisions.c.workspace_id == workspace_id,
                        tables.dataset_revisions.c.id == dataset_revision_id,
                    )
                )
            ).one_or_none()
        if revision is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy dataset revision trong scope")
        return [
            DatasetRowView(index=index, parameters=dict(row), row_digest=digest_content(row))
            for index, row in enumerate(revision.content.get("rows", []))
        ]
