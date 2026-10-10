from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from tests.support.p22 import run_with_calls
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction

from agentqa.contracts.models import MessagePurpose, ProviderRoute, Usage
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


async def test_usage_by_phase_finish_repair_retry_parallel(runtime) -> None:
    specs = [
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=100, output_tokens=40),
            "cost": "0.01",
            "basis": "provider_report",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.REPAIR,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=60, output_tokens=20),
            "cost": "0.006",
            "basis": "provider_report",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.FINISH,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=30, output_tokens=10),
            "cost": "0.003",
            "basis": "provider_report",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=100, output_tokens=40),
            "cost": "0.01",
            "basis": "provider_report",
        },
    ]
    user_id, workspace_id, run_id = await run_with_calls(runtime, call_specs=specs)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        phases = await runtime.usage.usage_by_phase(session, workspace_id=workspace_id, run_id=run_id)
        assert phases["decide"]["calls"] == 2
        assert phases["decide"]["input_tokens"] == 200
        assert phases["repair"]["calls"] == 1
        assert phases["finish"]["calls"] == 1
        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)
        assert aggregate.state == "complete"
        assert aggregate.missing_settled_calls == 0
        total = sum(entry.total for entry in aggregate.entries if entry.total is not None)
        assert total == Decimal("0.029")
        wall = await runtime.usage.wall_time_seconds(session, workspace_id=workspace_id, run_id=run_id)
        assert wall["wall_time_seconds"] >= 0
        assert wall["unknown_intervals"] == 0


async def test_missing_cost_and_unknown_call_stay_partial_not_zero(runtime) -> None:
    specs = [
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=10, output_tokens=5),
            "cost": "0.001",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=10, output_tokens=5),
        },
        {
            "route": ProviderRoute.OPENCODE_ZEN,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "jev-1.13-free",
            "unknown": True,
        },
    ]
    user_id, workspace_id, run_id = await run_with_calls(runtime, call_specs=specs)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)
        assert aggregate.state == "partial"
        assert aggregate.unknown_calls == 1
        assert aggregate.missing_settled_calls >= 1
        assert all(entry.total != Decimal("0") for entry in aggregate.entries if entry.total is not None)


async def test_cost_bases_are_separate_measures(runtime) -> None:
    specs = [
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=10, output_tokens=5),
            "cost": "0.002",
            "basis": "provider_report",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=10, output_tokens=5),
            "cost": "0.0015",
            "basis": "price_estimate",
        },
        {
            "route": ProviderRoute.OPENCODE_GO,
            "purpose": MessagePurpose.DECIDE,
            "requested_model": "deepseek-v4.1-flash",
            "usage": Usage(input_tokens=10, output_tokens=5),
            "cost": "0.0009",
            "basis": "subscription_allocation",
        },
    ]
    user_id, workspace_id, run_id = await run_with_calls(runtime, call_specs=specs)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        aggregate = await runtime.usage.aggregate_run(session, workspace_id=workspace_id, run_id=run_id)
        bases = {entry.basis for entry in aggregate.entries}
        assert bases == {"provider_report", "price_estimate", "subscription_allocation"}
        assert aggregate.state == "complete"


async def test_wall_time_is_union_not_sum_and_unknown_interval_counted(runtime) -> None:
    user_id, workspace_id, run_id = await run_with_calls(runtime, call_specs=[])
    start = datetime.now(UTC)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        import sqlalchemy as sa

        from agentqa.platform.storage import tables

        for offset, length in ((0, 10), (5, 10), (30, 5)):
            call_id = await runtime.usage.start_call(
                session,
                workspace_id=workspace_id,
                route=ProviderRoute.OPENCODE_GO,
                purpose=MessagePurpose.DECIDE,
                requested_model="deepseek-v4.1-flash",
                run_id=run_id,
            )
            await session.execute(
                sa.update(tables.model_calls)
                .where(tables.model_calls.c.id == call_id)
                .values(
                    started_at=start + timedelta(seconds=offset),
                    ended_at=start + timedelta(seconds=offset + length),
                )
            )
        unknown_call = await runtime.usage.start_call(
            session,
            workspace_id=workspace_id,
            route=ProviderRoute.OPENCODE_GO,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            run_id=run_id,
        )
        assert unknown_call is not None
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        wall = await runtime.usage.wall_time_seconds(session, workspace_id=workspace_id, run_id=run_id)
        assert wall["wall_time_seconds"] == 20.0
        assert wall["unknown_intervals"] == 1


async def test_price_snapshot_is_pinned_by_time(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        import sqlalchemy as sa

        from agentqa.platform.storage import tables

        before = datetime.now(UTC)
        old = uuid4()
        await session.execute(
            sa.insert(tables.price_snapshots).values(
                id=old,
                provider_route=ProviderRoute.OPENCODE_GO.value,
                model="deepseek-v4.1-flash",
                currency="USD",
                input_per_million="0.10",
                output_per_million="0.20",
                basis="price_estimate",
                source="bảng giá cũ",
                created_at=before - timedelta(days=30),
            )
        )
        await runtime.usage.record_price_snapshot(
            session,
            route=ProviderRoute.OPENCODE_GO,
            model="deepseek-v4.1-flash",
            currency="USD",
            basis="price_estimate",
            input_per_million="0.12",
            output_per_million="0.24",
            source="bảng giá mới",
        )
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        pinned = await runtime.usage.price_at(
            session, route=ProviderRoute.OPENCODE_GO, model="deepseek-v4.1-flash", at=before - timedelta(days=10)
        )
        assert pinned is not None
        assert pinned["input_per_million"] == Decimal("0.100000000000000000")
        latest = await runtime.usage.price_at(
            session, route=ProviderRoute.OPENCODE_GO, model="deepseek-v4.1-flash", at=before + timedelta(seconds=1)
        )
        assert latest is not None
        assert latest["input_per_million"] == Decimal("0.120000000000000000")
