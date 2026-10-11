from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from oracle.variants import stable_opportunity_id, variant_oracle_record
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.evaluation import EvaluationService, OracleOpportunity, OracleRecord, VariantClassification
from agentqa.platform.storage import tables
from tests.support.postgres import scoped_transaction, seed_workspace

pytestmark = pytest.mark.asyncio

PROBE = {"counters": {"item_deleted": 1}, "label_counts": {}, "last_write_ref": "item-1"}
NAMESPACE = "revision-ns"
ITEM_NAME = "Việc X"


def variant_record() -> OracleRecord:
    manifest = {
        "variant_token": "v-testtoken0000",
        "case_key": "taskboard_delete_item_healed",
        "app": "taskboard",
        "operator": {"name": "rename_label", "version": 1, "group": "benign"},
        "params": {"from": "Xoá", "to": "Xoá cũ"},
        "applied_patch": {"from": "Xoá", "to": "Xoá cũ"},
        "valid": True,
    }
    raw = variant_oracle_record(manifest)
    return OracleRecord(
        case_key=raw["case_key"],
        variant_token=raw["variant_token"],
        app=raw["app"],
        fixture_ref=raw["fixture_ref"],
        classification=VariantClassification(raw["classification"]),
        expected_effects=raw["expected_effects"],
        opportunities=[
            OracleOpportunity(
                opportunity_id=opportunity["opportunity_id"],
                step_id=opportunity["step_id"],
                original_identity=opportunity["original_identity"],
                expected_entity=opportunity.get("expected_entity"),
                kind=opportunity["kind"],
            )
            for opportunity in raw["opportunities"]
        ],
    )


def resolver(app: str, namespace: str, ref: str) -> str | None:
    if app == "taskboard":
        return ref
    from oracle.registry import resolve_ref

    return resolve_ref(app, namespace, ref)


async def seed_run(engines: dict[str, AsyncEngine]) -> tuple:
    user_id, workspace_id = await seed_workspace(engines, label=f"eval-{uuid4().hex[:8]}")
    run_id = uuid4()
    execution_id = uuid4()
    async with scoped_transaction(engines["agentqa_api"], principal_id=user_id, workspace_id=workspace_id) as session:
        await session.execute(
            sa.insert(tables.runs).values(
                id=run_id,
                workspace_id=workspace_id,
                status="succeeded",
                verdict="passed",
                gate="passed",
                reasons=["healed"],
            )
        )
        await session.execute(
            sa.insert(tables.run_snapshots).values(
                workspace_id=workspace_id,
                run_id=run_id,
                snapshot_version=1,
                content={"policy": "replay_healing"},
                content_digest="b" * 64,
            )
        )
        await session.execute(
            sa.insert(tables.executions).values(
                id=execution_id,
                workspace_id=workspace_id,
                run_id=run_id,
                logical_key="case-1",
                status="succeeded",
                verdict="passed",
                parameters={"item_name": ITEM_NAME},
            )
        )
        await session.execute(
            sa.insert(tables.run_events).values(
                workspace_id=workspace_id,
                run_id=run_id,
                run_seq=1,
                type="fixture.probed",
                actor="worker",
                summary={"probe": PROBE, "namespace": NAMESPACE, "fixture_ref": "taskboard@1"},
                payload_month=datetime.now(UTC).date().replace(day=1),
                recorded_at=datetime.now(UTC),
            )
        )
    return user_id, workspace_id, run_id, execution_id


async def add_healing_record(engines, *, user_id, workspace_id, run_id, execution_id, attempt_ref: str) -> None:
    async with scoped_transaction(
        engines["agentqa_worker"], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        await session.execute(
            sa.insert(tables.healing_records).values(
                workspace_id=workspace_id,
                run_id=run_id,
                execution_id=execution_id,
                attempt_id=uuid4(),
                actor="action",
                node_id="delete_item",
                opportunity_id=stable_opportunity_id("delete_item", "delete_item", "Xoá việc"),
                attempt_ref=attempt_ref,
                decision="recovered",
                original_target={"intent": "delete_item", "name": "Xoá"},
                actual_target={"intent": "delete_item", "name": "Xoá cũ"},
                dispatch_outcome="succeeded",
                guard_checks=["unique_target"],
                postconditions_ok=True,
                recorded_at=datetime.now(UTC),
            )
        )


async def test_scoring_revisions_keep_history_and_safe_views(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, run_id, execution_id = await seed_run(engines)
    await add_healing_record(
        engines, user_id=user_id, workspace_id=workspace_id, run_id=run_id, execution_id=execution_id, attempt_ref="a1"
    )
    service = EvaluationService(engines["agentqa_evaluator"], ref_resolver=resolver)
    first = await service.evaluate_run(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, oracle=variant_record()
    )
    assert first["revision_no"] == 1
    assert first["oracle_task_outcome"] == "true"
    assert first["false_pass"] is False
    assert first["counters"]["correct_heals"] == 1
    assert first["counters"]["detected"] == 1
    assert first["superseded_by"] is None

    await add_healing_record(
        engines, user_id=user_id, workspace_id=workspace_id, run_id=run_id, execution_id=execution_id, attempt_ref="a2"
    )
    second = await service.evaluate_run(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, oracle=variant_record()
    )
    assert second["revision_no"] == 2
    assert second["counters"]["attempts_total"] == 2

    results = await service.list_results(workspace_id=workspace_id, principal_id=user_id, run_id=run_id)
    assert [row["revision_no"] for row in results] == [1, 2]
    assert results[0]["superseded_by"] == second["id"]
    assert results[1]["superseded_by"] is None
    for row in results:
        assert "oracle" not in {key for key in row if key not in ("oracle_task_outcome", "oracle_digest")}
        assert "expected_effects" not in str(row["labels"])
        assert row["input_digest"] != row["oracle_digest"]


async def test_late_evidence_appends_revision_without_overwrite(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id, run_id, execution_id = await seed_run(engines)
    service = EvaluationService(engines["agentqa_evaluator"], ref_resolver=resolver)
    first = await service.evaluate_run(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, oracle=variant_record()
    )
    await add_healing_record(
        engines,
        user_id=user_id,
        workspace_id=workspace_id,
        run_id=run_id,
        execution_id=execution_id,
        attempt_ref="late",
    )
    second = await service.evaluate_run(
        workspace_id=workspace_id, principal_id=user_id, run_id=run_id, oracle=variant_record()
    )
    assert first["id"] != second["id"]
    assert first["counters"]["attempts_total"] == 0
    assert second["counters"]["attempts_total"] == 1
    async with scoped_transaction(
        engines["agentqa_evaluator"], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        rows = (
            await session.execute(
                sa.select(tables.evaluation_results.c.revision_no).where(
                    tables.evaluation_results.c.workspace_id == workspace_id,
                    tables.evaluation_results.c.run_id == run_id,
                )
            )
        ).all()
    assert sorted(row.revision_no for row in rows) == [1, 2]
