from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


@dataclass(frozen=True)
class ImpactLinkView:
    case_id: UUID
    logical_key: str
    case_revision_id: UUID
    revision_no: int
    needs_review: bool
    source_names: list[str]
    affected_assertions: list[str]
    affected_nodes: list[str]
    review_marked_at: datetime | None


@dataclass(frozen=True)
class RequirementImpactView:
    requirement_id: UUID
    logical_key: str
    latest_revision_no: int | None
    links: list[ImpactLinkView]


def _checkpoint_assertions(nodes: list[dict]) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for node in nodes:
        kind = node.get("kind")
        if kind == "checkpoint":
            for assertion in node.get("assertions", []):
                found.append((node.get("id", ""), assertion))
        elif kind == "branch":
            found.extend(_checkpoint_assertions(node.get("then_nodes", [])))
            found.extend(_checkpoint_assertions(node.get("else_nodes", [])))
        elif kind == "loop":
            found.extend(_checkpoint_assertions(node.get("body", [])))
    return found


def affected_by_sources(content: dict, source_names: set[str]) -> tuple[list[str], list[str]]:
    assertions: list[str] = []
    nodes: list[str] = []
    for node_id, assertion in _checkpoint_assertions(content.get("nodes", [])):
        refs = set(assertion.get("source_refs", []))
        if refs & source_names:
            assertions.append(assertion.get("id", ""))
            nodes.append(node_id)
    return sorted(set(assertions)), sorted(set(nodes))


class RequirementImpactService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._factory = create_session_factory(engine)

    async def impact(self, *, workspace_id: UUID, principal_id: UUID, requirement_id: UUID) -> RequirementImpactView:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            requirement = (
                await session.execute(
                    sa.select(tables.requirements.c.id, tables.requirements.c.logical_key).where(
                        tables.requirements.c.workspace_id == workspace_id,
                        tables.requirements.c.id == requirement_id,
                    )
                )
            ).one_or_none()
            if requirement is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy requirement trong scope")
            latest_revision = (
                await session.execute(
                    sa.select(tables.requirement_revisions.c.revision_no, tables.requirement_revisions.c.content)
                    .where(
                        tables.requirement_revisions.c.workspace_id == workspace_id,
                        tables.requirement_revisions.c.requirement_id == requirement_id,
                    )
                    .order_by(tables.requirement_revisions.c.revision_no.desc())
                    .limit(1)
                )
            ).one_or_none()
            links = (
                await session.execute(
                    sa.select(
                        tables.case_source_links.c.case_id,
                        tables.case_source_links.c.case_revision_id,
                        tables.case_source_links.c.needs_review,
                        tables.case_source_links.c.source_names,
                        tables.case_source_links.c.review_marked_at,
                        tables.case_revisions.c.revision_no,
                        tables.case_revisions.c.content,
                        tables.cases.c.logical_key,
                    )
                    .join(
                        tables.case_revisions,
                        (tables.case_revisions.c.id == tables.case_source_links.c.case_revision_id)
                        & (tables.case_revisions.c.workspace_id == tables.case_source_links.c.workspace_id),
                    )
                    .join(
                        tables.cases,
                        (tables.cases.c.id == tables.case_source_links.c.case_id)
                        & (tables.cases.c.workspace_id == tables.case_source_links.c.workspace_id),
                    )
                    .where(
                        tables.case_source_links.c.workspace_id == workspace_id,
                        tables.case_source_links.c.requirement_id == requirement_id,
                    )
                    .order_by(tables.cases.c.logical_key, tables.case_revisions.c.revision_no)
                )
            ).all()
        source_names = set(latest_revision.content.get("source_refs", [])) if latest_revision else set()
        link_views: list[ImpactLinkView] = []
        for row in links:
            affected_assertions, affected_nodes = affected_by_sources(row.content, source_names)
            link_views.append(
                ImpactLinkView(
                    case_id=row.case_id,
                    logical_key=row.logical_key,
                    case_revision_id=row.case_revision_id,
                    revision_no=row.revision_no,
                    needs_review=row.needs_review,
                    source_names=sorted(set(row.source_names) & source_names),
                    affected_assertions=affected_assertions,
                    affected_nodes=affected_nodes,
                    review_marked_at=row.review_marked_at,
                )
            )
        return RequirementImpactView(
            requirement_id=requirement.id,
            logical_key=requirement.logical_key,
            latest_revision_no=latest_revision.revision_no if latest_revision else None,
            links=link_views,
        )
