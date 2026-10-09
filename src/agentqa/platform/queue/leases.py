from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentqa.platform.storage.scope import set_scope
from agentqa.platform.storage.tables import executions, jobs, resource_slots, runs, worker_leases

DEFAULT_SLOT_SCOPE = "browser"
DEFAULT_SLOT_CAPACITY = 1


class QueueUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimResult:
    job_id: UUID
    lease_id: UUID
    epoch: int
    run_id: UUID | None
    execution_id: UUID | None
    resource_slot_id: UUID | None


class JobQueue:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        workspace_id: UUID,
        principal_id: UUID,
        slot_scope: str = DEFAULT_SLOT_SCOPE,
        slot_capacity: int = DEFAULT_SLOT_CAPACITY,
    ) -> None:
        self._factory = session_factory
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._slot_scope = slot_scope
        self._slot_capacity = slot_capacity

    def _transaction(self) -> Any:
        factory = self._factory
        principal_id = self._principal_id
        workspace_id = self._workspace_id

        class _Scope:
            async def __aenter__(self) -> AsyncSession:
                self._session = factory()
                await self._session.__aenter__()
                self._begin = self._session.begin()
                await self._begin.__aenter__()
                await set_scope(self._session, principal_id=principal_id, workspace_id=workspace_id)
                return self._session

            async def __aexit__(self, *exc_info: object) -> Any:
                try:
                    return await self._begin.__aexit__(*exc_info)
                finally:
                    await self._session.__aexit__(*exc_info)

        return _Scope()

    async def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
        require_slot: bool = True,
        job_kind: str = "browser_run",
    ) -> ClaimResult | None:
        interval = f"interval '{max(1, round(lease_seconds))} seconds'"
        try:
            async with self._transaction() as session:
                candidate = (
                    await session.execute(
                        sa.select(jobs.c.id, jobs.c.run_id, jobs.c.execution_id)
                        .where(
                            jobs.c.workspace_id == self._workspace_id,
                            jobs.c.state == "queued",
                            jobs.c.kind == job_kind,
                            jobs.c.available_at <= sa.func.now(),
                        )
                        .order_by(jobs.c.priority.desc(), jobs.c.available_at, jobs.c.id)
                        .limit(1)
                    )
                ).first()
                if candidate is None:
                    return None
                if candidate.run_id is not None:
                    await session.execute(sa.select(runs.c.id).where(runs.c.id == candidate.run_id).with_for_update())
                if candidate.execution_id is not None:
                    await session.execute(
                        sa.select(executions.c.id).where(executions.c.id == candidate.execution_id).with_for_update()
                    )
                job = (
                    await session.execute(
                        sa.select(jobs)
                        .where(
                            jobs.c.workspace_id == self._workspace_id,
                            jobs.c.id == candidate.id,
                            jobs.c.state == "queued",
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).first()
                if job is None:
                    return None
                slot_id = None
                if require_slot:
                    slot_id = await self._reserve_slot(session)
                    if slot_id is None:
                        return None
                epoch = job.claim_epoch + 1
                await session.execute(
                    sa.update(jobs)
                    .where(jobs.c.id == job.id)
                    .values(
                        state="claimed",
                        claimed_by=worker_id,
                        claim_epoch=epoch,
                        lease_expires_at=sa.text(f"now() + {interval}"),
                        updated_at=sa.func.now(),
                    )
                )
                lease = (
                    await session.execute(
                        sa.insert(worker_leases)
                        .values(
                            workspace_id=self._workspace_id,
                            job_id=job.id,
                            worker_id=worker_id,
                            epoch=epoch,
                            expires_at=sa.text(f"now() + {interval}"),
                        )
                        .returning(worker_leases.c.id)
                    )
                ).scalar_one()
                return ClaimResult(
                    job_id=job.id,
                    lease_id=lease,
                    epoch=epoch,
                    run_id=job.run_id,
                    execution_id=job.execution_id,
                    resource_slot_id=slot_id,
                )
        except SQLAlchemyError as exc:
            raise QueueUnavailable(str(exc)) from exc

    async def heartbeat(self, lease_id: UUID, *, lease_seconds: float = 30.0) -> bool:
        interval = f"interval '{max(1, round(lease_seconds))} seconds'"
        try:
            async with self._transaction() as session:
                lease = (
                    await session.execute(
                        sa.select(worker_leases)
                        .where(
                            worker_leases.c.workspace_id == self._workspace_id,
                            worker_leases.c.id == lease_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if lease is None or lease.released_at is not None:
                    return False
                alive = (
                    await session.execute(
                        sa.select(worker_leases.c.expires_at > sa.func.now()).where(worker_leases.c.id == lease_id)
                    )
                ).scalar_one()
                if not alive:
                    return False
                await session.execute(
                    sa.update(worker_leases)
                    .where(worker_leases.c.id == lease_id)
                    .values(heartbeat_at=sa.func.now(), expires_at=sa.text(f"now() + {interval}"))
                )
                return True
        except SQLAlchemyError as exc:
            raise QueueUnavailable(str(exc)) from exc

    async def release(self, lease_id: UUID, *, job_state: str = "succeeded") -> None:
        await self._finish_lease(lease_id, job_state=job_state, quarantine_reason=None)

    async def quarantine(self, lease_id: UUID, *, reason: str) -> None:
        await self._finish_lease(lease_id, job_state="quarantined", quarantine_reason=reason)

    async def admission_available(self) -> bool:
        try:
            async with self._transaction() as session:
                await session.execute(sa.select(sa.literal(1)))
                return True
        except SQLAlchemyError as exc:
            raise QueueUnavailable(str(exc)) from exc

    async def slot_state(self) -> dict[str, Any]:
        try:
            async with self._transaction() as session:
                row = (
                    await session.execute(
                        sa.select(resource_slots).where(
                            resource_slots.c.workspace_id == self._workspace_id,
                            resource_slots.c.scope == self._slot_scope,
                        )
                    )
                ).first()
                if row is None:
                    return {"capacity": self._slot_capacity, "reserved": 0}
                return {"capacity": row.capacity, "reserved": row.reserved}
        except SQLAlchemyError as exc:
            raise QueueUnavailable(str(exc)) from exc

    async def _reserve_slot(self, session: AsyncSession) -> UUID | None:
        row = (
            await session.execute(
                sa.select(resource_slots)
                .where(
                    resource_slots.c.workspace_id == self._workspace_id,
                    resource_slots.c.scope == self._slot_scope,
                    resource_slots.c.resource_key == str(self._workspace_id),
                )
                .with_for_update()
            )
        ).first()
        if row is None:
            await session.execute(
                pg_insert(resource_slots)
                .values(
                    workspace_id=self._workspace_id,
                    scope=self._slot_scope,
                    resource_key=str(self._workspace_id),
                    capacity=self._slot_capacity,
                    reserved=0,
                )
                .on_conflict_do_nothing(index_elements=["workspace_id", "scope", "resource_key"])
            )
            row = (
                await session.execute(
                    sa.select(resource_slots)
                    .where(
                        resource_slots.c.workspace_id == self._workspace_id,
                        resource_slots.c.scope == self._slot_scope,
                        resource_slots.c.resource_key == str(self._workspace_id),
                    )
                    .with_for_update()
                )
            ).first()
        if row is None or row.reserved >= row.capacity:
            return None
        await session.execute(
            sa.update(resource_slots).where(resource_slots.c.id == row.id).values(reserved=row.reserved + 1)
        )
        return row.id

    async def _finish_lease(self, lease_id: UUID, *, job_state: str, quarantine_reason: str | None) -> None:
        try:
            async with self._transaction() as session:
                lease = (
                    await session.execute(
                        sa.select(worker_leases)
                        .where(
                            worker_leases.c.workspace_id == self._workspace_id,
                            worker_leases.c.id == lease_id,
                        )
                        .with_for_update()
                    )
                ).first()
                if lease is None:
                    return
                await session.execute(
                    sa.update(worker_leases)
                    .where(worker_leases.c.id == lease_id, worker_leases.c.released_at.is_(None))
                    .values(released_at=sa.func.now())
                )
                await session.execute(
                    sa.update(jobs)
                    .where(jobs.c.id == lease.job_id)
                    .values(state=job_state, claimed_by=None, updated_at=sa.func.now())
                )
                if quarantine_reason is not None:
                    await session.execute(
                        sa.update(jobs)
                        .where(jobs.c.id == lease.job_id)
                        .values(
                            payload=sa.func.jsonb_set(
                                jobs.c.payload,
                                sa.cast(sa.literal("{quarantine_reason}"), postgresql.ARRAY(sa.Text)),
                                sa.func.to_jsonb(sa.literal(quarantine_reason)),
                            )
                        )
                    )
                slot = (
                    await session.execute(
                        sa.select(resource_slots)
                        .where(
                            resource_slots.c.workspace_id == self._workspace_id,
                            resource_slots.c.scope == self._slot_scope,
                            resource_slots.c.resource_key == str(self._workspace_id),
                        )
                        .with_for_update()
                    )
                ).first()
                if slot is not None and slot.reserved > 0:
                    await session.execute(
                        sa.update(resource_slots)
                        .where(resource_slots.c.id == slot.id)
                        .values(reserved=slot.reserved - 1)
                    )
        except SQLAlchemyError as exc:
            raise QueueUnavailable(str(exc)) from exc
