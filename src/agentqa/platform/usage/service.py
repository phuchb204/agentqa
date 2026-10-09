from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from agentqa.contracts.models import MessagePurpose, ModelCallOutcome, ProviderRoute, Usage
from agentqa.platform.storage import tables

USAGE_SEMANTICS_VERSION = "usage/1"

COST_BASES = ("provider_report", "price_estimate", "subscription_allocation")


@dataclass(frozen=True)
class CostAggregateEntry:
    basis: str
    currency: str
    total: Decimal | None
    settled_count: int
    unknown_count: int


@dataclass(frozen=True)
class CostAggregate:
    entries: tuple[CostAggregateEntry, ...]
    state: str
    missing_settled_calls: int
    unknown_calls: int


class UsageLedgerService:
    async def start_call(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        route: ProviderRoute,
        purpose: MessagePurpose,
        requested_model: str,
        run_id: UUID | None = None,
        execution_id: UUID | None = None,
        group_id: UUID | None = None,
        attempt: int = 1,
        payload_month=None,
    ) -> UUID:
        call_id = uuid4()
        await session.execute(
            sa.insert(tables.model_calls).values(
                id=call_id,
                workspace_id=workspace_id,
                run_id=run_id,
                execution_id=execution_id,
                group_id=group_id,
                attempt=attempt,
                purpose=purpose.value,
                requested_model=requested_model,
                route=route.value,
                record_state="started",
                payload_month=payload_month or _current_month(),
            )
        )
        return call_id

    async def settle_call(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        call_id: UUID,
        outcome: ModelCallOutcome,
        usage: Usage | None,
        resolved_model: str | None = None,
        error_code: str | None = None,
    ) -> None:
        values: dict = {
            "record_state": "settled",
            "outcome": outcome.value,
            "ended_at": datetime.now(UTC),
            "resolved_model": resolved_model,
            "error_code": error_code,
        }
        rows = 0
        if usage is not None:
            values.update(
                usage_input=usage.input_tokens,
                usage_output=usage.output_tokens,
                usage_cached=usage.cached_tokens,
                usage_basis="observed" if _has_observed(usage) else None,
            )
        result = await session.execute(
            sa.update(tables.model_calls)
            .where(tables.model_calls.c.id == call_id, tables.model_calls.c.workspace_id == workspace_id)
            .values(**values)
        )
        rows = result.rowcount
        if rows == 0:
            return
        if usage is None:
            await session.execute(
                sa.insert(tables.usage_entries).values(
                    workspace_id=workspace_id,
                    call_id=call_id,
                    semantics_version=USAGE_SEMANTICS_VERSION,
                    basis="null",
                )
            )
        else:
            await session.execute(
                sa.insert(tables.usage_entries).values(
                    workspace_id=workspace_id,
                    call_id=call_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cached_tokens=usage.cached_tokens,
                    semantics_version=USAGE_SEMANTICS_VERSION,
                    basis="observed" if _has_observed(usage) else "estimated",
                )
            )

    async def mark_unknown(self, session: AsyncSession, *, workspace_id: UUID, call_id: UUID, reason: str) -> None:
        await session.execute(
            sa.update(tables.model_calls)
            .where(tables.model_calls.c.id == call_id, tables.model_calls.c.workspace_id == workspace_id)
            .values(
                record_state="unknown",
                outcome=ModelCallOutcome.UNKNOWN.value,
                error_code=reason,
                ended_at=datetime.now(UTC),
            )
        )

    async def record_cost(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        basis: str,
        coverage: str,
        record_state: str,
        currency: str | None = None,
        amount: Decimal | str | None = None,
        call_id: UUID | None = None,
        run_id: UUID | None = None,
        execution_id: UUID | None = None,
        price_snapshot_id: UUID | None = None,
    ) -> UUID:
        if basis not in COST_BASES:
            raise ValueError(f"basis không hợp lệ: {basis}")
        entry_id = uuid4()
        await session.execute(
            sa.insert(tables.cost_entries).values(
                id=entry_id,
                workspace_id=workspace_id,
                run_id=run_id,
                execution_id=execution_id,
                call_id=call_id,
                amount=amount,
                currency=currency,
                basis=basis,
                price_snapshot_id=price_snapshot_id,
                coverage=coverage,
                record_state=record_state,
                settled_at=datetime.now(UTC) if record_state == "settled" else None,
            )
        )
        return entry_id

    async def aggregate_run(self, session: AsyncSession, *, workspace_id: UUID, run_id: UUID) -> CostAggregate:
        calls = (
            await session.execute(
                sa.select(tables.model_calls.c.id, tables.model_calls.c.record_state).where(
                    tables.model_calls.c.workspace_id == workspace_id,
                    tables.model_calls.c.run_id == run_id,
                )
            )
        ).all()
        settled_calls = {row.id for row in calls if row.record_state == "settled"}
        unknown_calls = sum(1 for row in calls if row.record_state == "unknown")

        entries = (
            await session.execute(
                sa.select(
                    tables.cost_entries.c.basis,
                    tables.cost_entries.c.currency,
                    tables.cost_entries.c.amount,
                    tables.cost_entries.c.record_state,
                    tables.cost_entries.c.call_id,
                ).where(
                    tables.cost_entries.c.workspace_id == workspace_id,
                    tables.cost_entries.c.run_id == run_id,
                )
            )
        ).all()

        grouped: dict[tuple[str, str], dict] = {}
        covered_calls: set = set()
        for row in entries:
            key = (row.basis, row.currency or "")
            bucket = grouped.setdefault(key, {"total": Decimal("0"), "any": False, "settled": 0, "unknown": 0})
            if row.record_state == "settled":
                bucket["settled"] += 1
                if row.amount is not None:
                    bucket["total"] += row.amount
                    bucket["any"] = True
                if row.call_id is not None:
                    covered_calls.add(row.call_id)
            elif row.record_state == "unknown":
                bucket["unknown"] += 1

        missing_settled = len(settled_calls - covered_calls)
        aggregate_entries = tuple(
            CostAggregateEntry(
                basis=basis,
                currency=currency,
                total=bucket["total"] if bucket["any"] else None,
                settled_count=bucket["settled"],
                unknown_count=bucket["unknown"],
            )
            for (basis, currency), bucket in sorted(grouped.items())
        )
        if (missing_settled or unknown_calls) and not aggregate_entries:
            state = "unknown"
        elif missing_settled or unknown_calls or any(entry.total is None for entry in aggregate_entries):
            state = "partial"
        else:
            state = "complete"
        return CostAggregate(
            entries=aggregate_entries,
            state=state,
            missing_settled_calls=missing_settled,
            unknown_calls=unknown_calls,
        )


def _has_observed(usage: Usage) -> bool:
    return any(value is not None for value in (usage.input_tokens, usage.output_tokens, usage.cached_tokens))


def _current_month():
    today = datetime.now(UTC).date()
    return today.replace(day=1)
