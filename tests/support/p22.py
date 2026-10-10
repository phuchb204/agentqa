from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.models import ModelCallOutcome
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction


async def terminal_run(
    runtime,
    *,
    verdict: str = "passed",
    gate: str = "passed",
    reasons: list[str] | None = None,
    assertion_result: str = "passed",
    with_artifacts: bool = False,
    workspace: tuple[UUID, UUID] | None = None,
) -> tuple[UUID, UUID, UUID]:
    if workspace is None:
        user_id, _username, workspace_id = await service_workspace(runtime)
    else:
        user_id, workspace_id = workspace
    run_id = uuid4()
    execution_id = uuid4()
    snapshot_content = {
        "policy": "replay_healing",
        "observation_mode": "semantic",
        "gate_profile": "strict",
        "cache_profile": "default",
        "calibration_ref": None,
        "content_digests": ["a" * 64],
        "environment_revision": str(uuid4()),
        "provisional": False,
    }
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await session.execute(
            sa.insert(tables.runs).values(
                id=run_id,
                workspace_id=workspace_id,
                status="succeeded" if verdict == "passed" else verdict,
                verdict=verdict,
                gate=gate,
                reasons=reasons or (["healed"] if verdict == "passed" else ["failed_assertion:item_exists_once"]),
            )
        )
        await session.execute(
            sa.insert(tables.run_snapshots).values(
                workspace_id=workspace_id,
                run_id=run_id,
                snapshot_version=1,
                content=snapshot_content,
                content_digest=digest_content(snapshot_content),
            )
        )
        await session.execute(
            sa.insert(tables.executions).values(
                id=execution_id,
                workspace_id=workspace_id,
                run_id=run_id,
                logical_key="terminal_case",
                status="succeeded",
                verdict=verdict,
            )
        )
        if with_artifacts:
            await session.execute(
                sa.insert(tables.artifacts).values(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    run_id=run_id,
                    kind="screenshot",
                    state="expired",
                    media_type="image/png",
                    redacted=True,
                    unavailable_reason="expired",
                )
            )
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await session.execute(
            sa.insert(tables.assertion_results).values(
                workspace_id=workspace_id,
                run_id=run_id,
                execution_id=execution_id,
                checkpoint_id="result",
                assertion_id="item_exists_once",
                result=assertion_result,
                proof_ref=json.dumps(
                    {
                        "expected": "1",
                        "observed": "0" if assertion_result != "passed" else "1",
                        "evidence": "present",
                        "applicable": True,
                        "reason": None,
                    }
                ),
            )
        )
    return user_id, workspace_id, run_id


async def run_with_calls(runtime, *, call_specs: list[dict]) -> tuple[UUID, UUID, UUID]:
    user_id, workspace_id, run_id = await terminal_run(runtime)
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        for spec in call_specs:
            call_id = await runtime.usage.start_call(
                session,
                workspace_id=workspace_id,
                route=spec["route"],
                purpose=spec["purpose"],
                requested_model=spec["requested_model"],
                run_id=run_id,
            )
            if spec.get("unknown"):
                await runtime.usage.mark_unknown(session, workspace_id=workspace_id, call_id=call_id, reason="timeout")
                continue
            await runtime.usage.settle_call(
                session,
                workspace_id=workspace_id,
                call_id=call_id,
                outcome=ModelCallOutcome(spec.get("outcome", "succeeded")),
                usage=spec.get("usage"),
                resolved_model=spec.get("resolved_model"),
            )
            if spec.get("cost") is not None:
                await runtime.usage.record_cost(
                    session,
                    workspace_id=workspace_id,
                    basis=spec.get("basis", "price_estimate"),
                    coverage=spec.get("coverage", "complete"),
                    record_state="settled",
                    currency=spec.get("currency", "USD"),
                    amount=Decimal(spec["cost"]),
                    call_id=call_id,
                    run_id=run_id,
                )
    return user_id, workspace_id, run_id
