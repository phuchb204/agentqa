from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.case import FixtureReceipt
from agentqa.platform.fixtures.registry import FixtureRegistry
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 2.0


@dataclass(frozen=True)
class FixtureRunClaim:
    record_id: UUID
    workspace_id: UUID
    run_id: UUID | None
    execution_id: UUID | None
    attempt_id: UUID | None
    fixture_ref: str
    namespace: str
    action: str
    attempts: int
    max_attempts: int


class FixtureRunService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        registry: FixtureRegistry,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._registry = registry
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    async def record_lifecycle(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_id: UUID | None,
        execution_id: UUID | None,
        attempt_id: UUID | None,
        receipt: FixtureReceipt,
        seed: str | None = None,
    ) -> UUID:
        detail: dict[str, Any] = {"receipt_detail": receipt.detail}
        if seed is not None:
            detail["seed"] = seed
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            record_id = (
                await session.execute(
                    sa.insert(tables.fixture_runs)
                    .values(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                        fixture_ref=receipt.fixture_ref,
                        namespace=receipt.namespace,
                        action=receipt.action,
                        state="succeeded" if receipt.ok else "failed",
                        attempts=1,
                        max_attempts=self._max_attempts,
                        detail=detail,
                    )
                    .returning(tables.fixture_runs.c.id)
                )
            ).scalar_one()
        return record_id

    async def enqueue_cleanup(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        run_id: UUID | None,
        execution_id: UUID | None,
        attempt_id: UUID | None,
        fixture_ref: str,
        namespace: str,
    ) -> UUID:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            if execution_id is not None:
                existing = (
                    await session.execute(
                        sa.select(tables.fixture_runs.c.id).where(
                            tables.fixture_runs.c.execution_id == execution_id,
                            tables.fixture_runs.c.action == "cleanup",
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return existing
            record_id = (
                await session.execute(
                    sa.insert(tables.fixture_runs)
                    .values(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                        fixture_ref=fixture_ref,
                        namespace=namespace,
                        action="cleanup",
                        state="pending",
                        attempts=0,
                        max_attempts=self._max_attempts,
                    )
                    .returning(tables.fixture_runs.c.id)
                )
            ).scalar_one()
        return record_id

    async def claim_due(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        worker_id: str,
        limit: int = 10,
        lease_seconds: float = 30.0,
    ) -> list[FixtureRunClaim]:
        interval = f"interval '{max(1, round(lease_seconds))} seconds'"
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.fixture_runs)
                    .where(
                        tables.fixture_runs.c.action == "cleanup",
                        sa.or_(
                            sa.and_(
                                tables.fixture_runs.c.state == "pending",
                                tables.fixture_runs.c.available_at <= sa.func.now(),
                            ),
                            sa.and_(
                                tables.fixture_runs.c.state == "running",
                                tables.fixture_runs.c.lease_expires_at < sa.func.now(),
                            ),
                        ),
                    )
                    .order_by(tables.fixture_runs.c.available_at, tables.fixture_runs.c.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims: list[FixtureRunClaim] = []
            for row in rows:
                await session.execute(
                    sa.update(tables.fixture_runs)
                    .where(tables.fixture_runs.c.id == row.id)
                    .values(
                        state="running",
                        claimed_by=worker_id,
                        claim_epoch=row.claim_epoch + 1,
                        lease_expires_at=sa.text(f"now() + {interval}"),
                        updated_at=sa.func.now(),
                    )
                )
                claims.append(
                    FixtureRunClaim(
                        record_id=row.id,
                        workspace_id=row.workspace_id,
                        run_id=row.run_id,
                        execution_id=row.execution_id,
                        attempt_id=row.attempt_id,
                        fixture_ref=row.fixture_ref,
                        namespace=row.namespace,
                        action=row.action,
                        attempts=row.attempts,
                        max_attempts=row.max_attempts,
                    )
                )
        return claims

    async def settle(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        claim: FixtureRunClaim,
        receipt: FixtureReceipt,
    ) -> str:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            if receipt.ok:
                state = "succeeded"
                attempts = claim.attempts + 1
                values: dict[str, Any] = {
                    "state": state,
                    "attempts": attempts,
                    "claimed_by": None,
                    "lease_expires_at": None,
                    "detail": {"receipt_detail": receipt.detail},
                    "updated_at": sa.func.now(),
                }
            else:
                attempts = claim.attempts + 1
                if attempts >= claim.max_attempts:
                    state = "exhausted"
                    values = {
                        "state": state,
                        "attempts": attempts,
                        "claimed_by": None,
                        "lease_expires_at": None,
                        "detail": {"receipt_detail": receipt.detail},
                        "updated_at": sa.func.now(),
                    }
                else:
                    state = "pending"
                    delay = self._backoff_seconds * attempts
                    values = {
                        "state": state,
                        "attempts": attempts,
                        "claimed_by": None,
                        "lease_expires_at": None,
                        "available_at": sa.text(f"now() + interval '{float(delay)} seconds'"),
                        "detail": {"receipt_detail": receipt.detail},
                        "updated_at": sa.func.now(),
                    }
            await session.execute(
                sa.update(tables.fixture_runs).where(tables.fixture_runs.c.id == claim.record_id).values(**values)
            )
        return state

    async def process_due(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        worker_id: str,
        limit: int = 10,
        lease_seconds: float = 30.0,
    ) -> list[dict[str, Any]]:
        claims = await self.claim_due(
            workspace_id=workspace_id,
            principal_id=principal_id,
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        results: list[dict[str, Any]] = []
        for claim in claims:
            try:
                receipt = self._registry.cleanup(claim.fixture_ref, claim.namespace)
            except Exception as exc:
                receipt = FixtureReceipt(
                    fixture_ref=claim.fixture_ref,
                    namespace=claim.namespace,
                    action="cleanup",
                    ok=False,
                    detail=f"exception:{type(exc).__name__}",
                )
            state = await self.settle(
                workspace_id=workspace_id, principal_id=principal_id, claim=claim, receipt=receipt
            )
            results.append(
                {
                    "record_id": claim.record_id,
                    "execution_id": claim.execution_id,
                    "state": state,
                    "attempts": claim.attempts + 1,
                }
            )
        return results
