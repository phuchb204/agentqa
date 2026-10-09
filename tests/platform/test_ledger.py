from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction

from agentqa.contracts.models import MessagePurpose, ModelCallOutcome, ProviderRoute, Usage
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


async def _setup_run(runtime):
    user_id, _username, workspace_id = await service_workspace(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        run_id = (
            await session.execute(
                sa.insert(tables.runs).values(workspace_id=workspace_id, status="running").returning(tables.runs.c.id)
            )
        ).scalar_one()
    return user_id, workspace_id, run_id


async def test_call_records_started_settled_and_unknown(runtime) -> None:
    user_id, workspace_id, run_id = await _setup_run(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        call_ok = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        started = (await session.execute(sa.select(tables.model_calls).where(tables.model_calls.c.id == call_ok))).one()
        assert started.record_state == "started"
        assert started.outcome is None

        await runtime.usage.settle_call(
            session,
            workspace_id=workspace_id,
            call_id=call_ok,
            outcome=ModelCallOutcome.SUCCEEDED,
            usage=Usage(input_tokens=120, output_tokens=40, cached_tokens=None),
        )
        settled = (await session.execute(sa.select(tables.model_calls).where(tables.model_calls.c.id == call_ok))).one()
        assert settled.record_state == "settled"
        assert settled.outcome == "succeeded"
        assert settled.usage_input == 120
        assert settled.usage_basis == "observed"

        call_null = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_ZEN,
            purpose=MessagePurpose.OBSERVE,
            requested_model="jev-1.13-free",
            run_id=run_id,
        )
        await runtime.usage.settle_call(
            session,
            workspace_id=workspace_id,
            call_id=call_null,
            outcome=ModelCallOutcome.SUCCEEDED,
            usage=None,
        )
        null_row = (
            await session.execute(sa.select(tables.model_calls).where(tables.model_calls.c.id == call_null))
        ).one()
        assert null_row.usage_basis is None
        assert null_row.usage_input is None

        call_unknown = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.PROPOSE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        await runtime.usage.mark_unknown(
            session, workspace_id=workspace_id, call_id=call_unknown, reason="provider_timeout"
        )
        unknown_row = (
            await session.execute(sa.select(tables.model_calls).where(tables.model_calls.c.id == call_unknown))
        ).one()
        assert unknown_row.record_state == "unknown"
        assert unknown_row.outcome == "unknown"

        usage_rows = (
            await session.execute(
                sa.select(tables.usage_entries.c.call_id, tables.usage_entries.c.basis).where(
                    tables.usage_entries.c.call_id.in_([call_ok, call_null])
                )
            )
        ).all()
    bases = {row.call_id: row.basis for row in usage_rows}
    assert bases[call_ok] == "observed"
    assert bases[call_null] == "null"


async def test_cost_ledger_basis_and_missingness(runtime) -> None:
    user_id, workspace_id, run_id = await _setup_run(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        covered = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        await runtime.usage.settle_call(
            session,
            workspace_id=workspace_id,
            call_id=covered,
            outcome=ModelCallOutcome.SUCCEEDED,
            usage=Usage(input_tokens=10, output_tokens=5),
        )
        await runtime.usage.record_cost(
            session,
            workspace_id=workspace_id,
            call_id=covered,
            run_id=run_id,
            basis="provider_report",
            coverage="complete",
            record_state="settled",
            currency="USD",
            amount=Decimal("0.25"),
        )
        missing = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_ZEN,
            purpose=MessagePurpose.OBSERVE,
            requested_model="jev-1.13-free",
            run_id=run_id,
        )
        await runtime.usage.settle_call(
            session,
            workspace_id=workspace_id,
            call_id=missing,
            outcome=ModelCallOutcome.SUCCEEDED,
            usage=None,
        )
        unknown = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.PROPOSE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        await runtime.usage.mark_unknown(session, workspace_id=workspace_id, call_id=unknown, reason="provider_timeout")

        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)

    assert aggregate.state == "partial"
    assert aggregate.missing_settled_calls == 1
    assert aggregate.unknown_calls == 1
    entry = next(item for item in aggregate.entries if item.basis == "provider_report")
    assert entry.currency == "USD"
    assert entry.total == Decimal("0.25")
    assert entry.total != Decimal("0")


async def test_cost_bases_are_separate_measures(runtime) -> None:
    user_id, workspace_id, run_id = await _setup_run(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        call = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        await runtime.usage.settle_call(
            session,
            workspace_id=workspace_id,
            call_id=call,
            outcome=ModelCallOutcome.SUCCEEDED,
            usage=None,
        )
        await runtime.usage.record_cost(
            session,
            workspace_id=workspace_id,
            call_id=call,
            run_id=run_id,
            basis="price_estimate",
            coverage="partial",
            record_state="settled",
            currency="USD",
            amount=Decimal("0.10"),
        )
        await runtime.usage.record_cost(
            session,
            workspace_id=workspace_id,
            call_id=call,
            run_id=run_id,
            basis="subscription_allocation",
            coverage="complete",
            record_state="settled",
            currency="USD",
            amount=None,
        )
        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)
    bases = {entry.basis for entry in aggregate.entries}
    assert bases == {"price_estimate", "subscription_allocation"}
    allocation = next(item for item in aggregate.entries if item.basis == "subscription_allocation")
    assert allocation.total is None
    assert aggregate.state == "partial"


async def test_missing_cost_is_never_zero(runtime) -> None:
    user_id, workspace_id, run_id = await _setup_run(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        call = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        await runtime.usage.mark_unknown(session, workspace_id=workspace_id, call_id=call, reason="lease_lost")
        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)
    assert aggregate.state == "unknown"
    assert aggregate.entries == ()
    assert aggregate.unknown_calls == 1
