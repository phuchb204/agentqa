from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope


class ExplorationPort(Protocol):
    async def open(self, base_url: str) -> None: ...

    async def snapshot(self, url: str) -> dict: ...

    async def attempt_write(self, url: str) -> bool: ...


@dataclass(frozen=True)
class ExplorationOutcome:
    job_id: UUID
    state: str
    error_reason: str | None
    environment_revision_id: UUID | None
    write_allowed: bool
    pages: list[dict]
    actions: list[dict]
    coverage_gaps: list[dict]
    proposals: list[dict]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class ExplorationService:
    def __init__(self, engine: AsyncEngine, *, port: ExplorationPort | None = None) -> None:
        self._factory = create_session_factory(engine)
        self._port = port

    async def create_job(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        environment_revision_id: UUID,
        goal: str,
        max_pages: int = 20,
        max_depth: int = 2,
    ) -> ExplorationOutcome:
        if self._port is None:
            raise IdentityError(ErrorCode.CAPABILITY_UNAVAILABLE, "Exploration port chưa được cấu hình")
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            environment = (
                await session.execute(
                    sa.select(tables.environment_revisions).where(
                        tables.environment_revisions.c.workspace_id == workspace_id,
                        tables.environment_revisions.c.id == environment_revision_id,
                        tables.environment_revisions.c.lifecycle == "ready",
                    )
                )
            ).one_or_none()
        if environment is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy environment revision trong scope")
        content = dict(environment.content or {})
        base_url = str(content.get("base_url", ""))
        if not base_url:
            raise IdentityError(ErrorCode.INPUT_INVALID, "Environment thiếu base_url")
        allowed_origins = frozenset([*content.get("allowed_origins", []), _origin(base_url)])
        write_allowed = bool(content.get("allow_write_actions", False))
        job_id = uuid4()
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.insert(tables.authoring_jobs).values(
                    id=job_id,
                    workspace_id=workspace_id,
                    kind="exploration",
                    state="running",
                    input={
                        "goal": goal,
                        "environment_revision_id": str(environment_revision_id),
                        "base_url": base_url,
                        "allowed_origins": sorted(allowed_origins),
                        "write_allowed": write_allowed,
                        "max_pages": max_pages,
                        "max_depth": max_depth,
                    },
                    started_at=datetime.now(UTC),
                )
            )
        await self._port.open(base_url)
        visited: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(base_url, 0)]
        pages: list[dict] = []
        actions: list[dict] = []
        gaps: list[dict] = []
        gap_keys: set[tuple[str, str]] = set()

        def add_gap(kind: str, url: str, reason: str) -> None:
            key = (kind, url)
            if key not in gap_keys:
                gap_keys.add(key)
                gaps.append({"kind": kind, "url": url, "reason": reason})

        while queue and len(pages) < max_pages:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited[url] = depth
            snapshot = await self._port.snapshot(url)
            links = [str(link) for link in snapshot.get("links", [])]
            pages.append(
                {
                    "url": url,
                    "title": str(snapshot.get("title", "")),
                    "depth": depth,
                    "links_total": len(links),
                }
            )
            if int(snapshot.get("forms", 0)) > 0:
                attempted = write_allowed
                actions.append(
                    {
                        "url": url,
                        "kind": "write",
                        "attempted": attempted,
                        "allowed": write_allowed,
                        "reason": None if write_allowed else "write_actions_disabled",
                    }
                )
                if attempted:
                    await self._port.attempt_write(url)
            for link in links:
                resolved = urljoin(url, link)
                if _origin(resolved) not in allowed_origins:
                    add_gap("external_origin", resolved, "blocked_external_origin")
                    continue
                if resolved in visited:
                    continue
                if depth + 1 > max_depth:
                    add_gap("depth_limit", resolved, "max_depth_reached")
                    continue
                if len(visited) + len(queue) >= max_pages:
                    add_gap("page_limit", resolved, "max_pages_reached")
                    continue
                queue.append((resolved, depth + 1))
        proposals = [
            {
                "title": f"Kiểm tra form tại {page['url']}",
                "entry_url": page["url"],
                "kind": "positive",
                "note": "exploration_proposal",
            }
            for page in pages
            if any(action["url"] == page["url"] for action in actions)
        ]
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            await session.execute(
                sa.insert(tables.exploration_results).values(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    environment_revision_id=environment_revision_id,
                    write_allowed=write_allowed,
                    pages=pages,
                    actions=actions,
                    coverage_gaps=gaps,
                    proposals=proposals,
                )
            )
            await session.execute(
                sa.update(tables.authoring_jobs)
                .where(tables.authoring_jobs.c.workspace_id == workspace_id, tables.authoring_jobs.c.id == job_id)
                .values(state="succeeded", finished_at=datetime.now(UTC))
            )
        return ExplorationOutcome(
            job_id=job_id,
            state="succeeded",
            error_reason=None,
            environment_revision_id=environment_revision_id,
            write_allowed=write_allowed,
            pages=pages,
            actions=actions,
            coverage_gaps=gaps,
            proposals=proposals,
        )

    async def get_job(self, *, workspace_id: UUID, principal_id: UUID, job_id: UUID) -> ExplorationOutcome:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            job = (
                await session.execute(
                    sa.select(tables.authoring_jobs).where(
                        tables.authoring_jobs.c.workspace_id == workspace_id,
                        tables.authoring_jobs.c.id == job_id,
                        tables.authoring_jobs.c.kind == "exploration",
                    )
                )
            ).one_or_none()
            if job is None:
                raise IdentityError(ErrorCode.NOT_FOUND, "Không tìm thấy exploration job trong scope")
            result = (
                await session.execute(
                    sa.select(tables.exploration_results).where(
                        tables.exploration_results.c.workspace_id == workspace_id,
                        tables.exploration_results.c.job_id == job_id,
                    )
                )
            ).one_or_none()
        return ExplorationOutcome(
            job_id=job.id,
            state=job.state,
            error_reason=job.error_reason,
            environment_revision_id=result.environment_revision_id if result is not None else None,
            write_allowed=bool(result.write_allowed) if result is not None else False,
            pages=list(result.pages) if result is not None else [],
            actions=list(result.actions) if result is not None else [],
            coverage_gaps=list(result.coverage_gaps) if result is not None else [],
            proposals=list(result.proposals) if result is not None else [],
        )
