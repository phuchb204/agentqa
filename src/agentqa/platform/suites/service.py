from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


@dataclass(frozen=True)
class PlannedExecution:
    execution_key: str
    case_logical_key: str
    case_revision_id: UUID | None
    dataset_row_index: int | None
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SuiteBindResult:
    suite_revision_id: UUID
    suite_logical_key: str
    fixture_refs: list[str]
    executions: list[PlannedExecution]
    facts: list[str]


class SuiteService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def bind(self, *, workspace_id: UUID, principal_id: UUID, suite_revision_id: UUID) -> SuiteBindResult:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            revision = (
                await session.execute(
                    sa.select(tables.suite_revisions, tables.suites.c.logical_key)
                    .join(
                        tables.suites,
                        (tables.suites.c.workspace_id == tables.suite_revisions.c.workspace_id)
                        & (tables.suites.c.id == tables.suite_revisions.c.suite_id),
                    )
                    .where(
                        tables.suite_revisions.c.workspace_id == workspace_id,
                        tables.suite_revisions.c.id == suite_revision_id,
                    )
                )
            ).one_or_none()
            if revision is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy suite revision trong scope")
            content = dict(revision.content or {})
            rows: list[dict | None] = [None]
            dataset_ref = content.get("dataset_ref")
            if dataset_ref:
                dataset = (
                    await session.execute(
                        sa.select(tables.datasets.c.id).where(
                            tables.datasets.c.workspace_id == workspace_id,
                            tables.datasets.c.logical_key == dataset_ref,
                        )
                    )
                ).one_or_none()
                if dataset is None:
                    rows = []
                else:
                    latest = (
                        await session.execute(
                            sa.select(tables.dataset_revisions.c.content)
                            .where(
                                tables.dataset_revisions.c.workspace_id == workspace_id,
                                tables.dataset_revisions.c.dataset_id == dataset.id,
                                tables.dataset_revisions.c.lifecycle == "ready",
                            )
                            .order_by(tables.dataset_revisions.c.revision_no.desc())
                            .limit(1)
                        )
                    ).one_or_none()
                    rows = list(latest.content.get("rows", [])) if latest is not None else []
            facts: list[str] = []
            executions: list[PlannedExecution] = []
            for ref in content.get("case_refs", []):
                key = str(ref.get("logical_key"))
                revision_no = int(ref.get("revision_no", 1))
                case_row = (
                    await session.execute(
                        sa.select(tables.cases.c.id).where(
                            tables.cases.c.workspace_id == workspace_id,
                            tables.cases.c.logical_key == key,
                        )
                    )
                ).one_or_none()
                case_revision_id = None
                if case_row is None:
                    facts.append(f"missing_case:{key}")
                else:
                    case_revision = (
                        await session.execute(
                            sa.select(tables.case_revisions.c.id).where(
                                tables.case_revisions.c.workspace_id == workspace_id,
                                tables.case_revisions.c.case_id == case_row.id,
                                tables.case_revisions.c.revision_no == revision_no,
                                tables.case_revisions.c.lifecycle == "ready",
                            )
                        )
                    ).one_or_none()
                    if case_revision is None:
                        facts.append(f"missing_case_revision:{key}@{revision_no}")
                    else:
                        case_revision_id = case_revision.id
                if dataset_ref and not rows:
                    facts.append(f"missing_dataset_rows:{dataset_ref}")
                for index, row in enumerate(rows):
                    row_index = index if row is not None else None
                    suffix = f"row{row_index}" if row_index is not None else "single"
                    executions.append(
                        PlannedExecution(
                            execution_key=f"{suite_revision_id}:{key}:{revision_no}:{suffix}",
                            case_logical_key=key,
                            case_revision_id=case_revision_id,
                            dataset_row_index=row_index,
                            parameters=dict(row) if row is not None else {},
                        )
                    )
        return SuiteBindResult(
            suite_revision_id=suite_revision_id,
            suite_logical_key=revision.logical_key,
            fixture_refs=list(content.get("fixture_refs", [])),
            executions=executions,
            facts=sorted(set(facts)),
        )
