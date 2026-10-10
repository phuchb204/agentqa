from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables


@dataclass(frozen=True)
class MaterializedExecution:
    execution_key: str
    case_logical_key: str
    case_id: UUID | None
    case_revision_id: UUID | None
    dataset_row_index: int | None
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SuiteMaterialization:
    suite_revision_id: UUID
    suite_logical_key: str
    suite_content_digest: str
    dataset_revision_id: UUID | None
    dataset_content_digest: str | None
    fixture_refs: list[str]
    fail_fast: bool
    executions: list[MaterializedExecution]
    facts: list[str]


async def materialize_suite(
    session: AsyncSession, *, workspace_id: UUID, suite_revision_id: UUID
) -> SuiteMaterialization:
    revision = (
        await session.execute(
            sa.select(
                tables.suite_revisions.c.content,
                tables.suite_revisions.c.content_digest,
                tables.suites.c.logical_key,
            )
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
    facts: list[str] = []
    rows: list[dict | None] = [None]
    dataset_revision_id: UUID | None = None
    dataset_content_digest: str | None = None
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
            facts.append(f"missing_dataset:{dataset_ref}")
            rows = []
        else:
            dataset_revision_no = content.get("dataset_revision_no")
            query = sa.select(
                tables.dataset_revisions.c.id,
                tables.dataset_revisions.c.content,
                tables.dataset_revisions.c.content_digest,
            ).where(
                tables.dataset_revisions.c.workspace_id == workspace_id,
                tables.dataset_revisions.c.dataset_id == dataset.id,
                tables.dataset_revisions.c.lifecycle == "ready",
            )
            if dataset_revision_no is not None:
                query = query.where(tables.dataset_revisions.c.revision_no == int(dataset_revision_no))
                latest = (await session.execute(query)).one_or_none()
                if latest is None:
                    facts.append(f"missing_dataset_revision:{dataset_ref}@{dataset_revision_no}")
                    rows = []
                else:
                    dataset_revision_id = latest.id
                    dataset_content_digest = latest.content_digest
                    rows = list((latest.content or {}).get("rows", []))
            else:
                latest = (
                    await session.execute(query.order_by(tables.dataset_revisions.c.revision_no.desc()).limit(1))
                ).one_or_none()
                if latest is None:
                    facts.append(f"missing_dataset_rows:{dataset_ref}")
                    rows = []
                else:
                    dataset_revision_id = latest.id
                    dataset_content_digest = latest.content_digest
                    rows = list((latest.content or {}).get("rows", []))
    executions: list[MaterializedExecution] = []
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
        case_id: UUID | None = None
        case_revision_id: UUID | None = None
        if case_row is None:
            facts.append(f"missing_case:{key}")
        else:
            case_id = case_row.id
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
                MaterializedExecution(
                    execution_key=f"{suite_revision_id}:{key}:{revision_no}:{suffix}",
                    case_logical_key=key,
                    case_id=case_id,
                    case_revision_id=case_revision_id,
                    dataset_row_index=row_index,
                    parameters=dict(row) if row is not None else {},
                )
            )
    return SuiteMaterialization(
        suite_revision_id=suite_revision_id,
        suite_logical_key=revision.logical_key,
        suite_content_digest=revision.content_digest,
        dataset_revision_id=dataset_revision_id,
        dataset_content_digest=dataset_content_digest,
        fixture_refs=list(content.get("fixture_refs", [])),
        fail_fast=bool(content.get("fail_fast", False)),
        executions=executions,
        facts=sorted(set(facts)),
    )
