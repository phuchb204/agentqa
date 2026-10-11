from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from oracle.publish import publish_records
from oracle.variants import publish_variant_manifests, variant_oracle_record
from sqlalchemy.exc import OperationalError, ProgrammingError

from agentqa.platform.evaluation import EvaluationInput, OracleRecord, VariantClassification, score
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ORACLE_DATABASE
from tests.support.postgres import scoped_transaction, seed_workspace
from tests.support.taskboard import TaskboardServer

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = REPO_ROOT / "benchmarks" / "public"
PUBLIC_TOKEN_KEYS = {"schema_version", "variant_token", "app", "fixture_ref", "build_digest"}
FORBIDDEN_PUBLIC_KEYS = ("applied_patch", "expected_effects", "opportunities", "oracle_assertions_ref", "operator")


def test_public_tree_contains_no_oracle_truth() -> None:
    token_files = (
        list((PUBLIC_ROOT / "variant-tokens").rglob("*.json")) if (PUBLIC_ROOT / "variant-tokens").exists() else []
    )
    for path in token_files:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == PUBLIC_TOKEN_KEYS, path
    for path in list(PUBLIC_ROOT.rglob("*.yaml")) + list(PUBLIC_ROOT.rglob("*.json")):
        if path.name == "inventory.yaml" or "variant-tokens" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_PUBLIC_KEYS:
            if forbidden == "operator":
                continue
            assert forbidden not in text, (path, forbidden)


def test_public_snapshot_cannot_leak_operator_into_prompt_context() -> None:
    snapshot = {
        "schema_version": "variant-token/1",
        "variant_token": "v-0000000000000000",
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "build_digest": "c" * 64,
    }
    prompt_context = f"Biến thể đang chạy: {json.dumps(snapshot, ensure_ascii=False)}"
    for leak in ("rename_label", "distractor", "business_bug", "expected", "patch", "operator"):
        assert leak not in prompt_context


def test_mutated_dom_has_no_mutation_markers(taskboard_server: TaskboardServer) -> None:
    namespace = "leak-marks"
    with httpx.Client(base_url=taskboard_server.base_url, follow_redirects=True, timeout=5.0) as client:
        response = client.post(
            f"{taskboard_server.base_url}/_control/namespaces/{namespace}/prepare",
            json={"accounts": {"alice": "pw"}, "items": [{"label": "Việc giống nhau"}, {"label": "Việc giống nhau"}]},
            headers={"x-taskboard-control": taskboard_server.control_token},
        )
        response.raise_for_status()
        response = client.post(
            f"{taskboard_server.base_url}/_control/namespaces/{namespace}/mutate",
            json={"operator": "rename_label", "params": {"from": "Xoá", "to": "Xoá cũ"}},
            headers={"x-taskboard-control": taskboard_server.control_token},
        )
        response.raise_for_status()
        login = client.post(f"/{namespace}/login", data={"username": "alice", "password": "pw"})
        assert login.status_code == 200
        html = client.get(f"{taskboard_server.base_url}/{namespace}/tasks").text
    for marker in ("rename_label", "mutation", "applied_patch", "data-mutation"):
        assert marker not in html, marker
    assert "Xoá cũ" in html


def test_worker_role_cannot_read_evaluation_results(test_db) -> None:
    import asyncio

    from agentqa.platform.storage.database import create_engine

    async def run() -> None:
        roles = ("agentqa_migrate", "agentqa_api", "agentqa_worker", "agentqa_supervisor", "agentqa_evaluator")
        engines = {role: create_engine(test_db.dsn(role), pool_size=2) for role in roles}
        try:
            user_id, workspace_id = await seed_workspace(engines, label=f"leak-{uuid4().hex[:8]}")
            run_id = uuid4()
            async with scoped_transaction(
                engines["agentqa_api"], principal_id=user_id, workspace_id=workspace_id
            ) as session:
                await session.execute(
                    sa.insert(tables.runs).values(
                        id=run_id, workspace_id=workspace_id, status="succeeded", verdict="passed"
                    )
                )
            async with scoped_transaction(
                engines["agentqa_evaluator"], principal_id=user_id, workspace_id=workspace_id
            ) as session:
                await session.execute(
                    sa.insert(tables.evaluation_results).values(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        revision_no=1,
                        evaluator_version="evaluator/1",
                        schema_version="evaluation/1",
                        input_digest="a" * 64,
                        oracle_digest="b" * 64,
                        oracle_task_outcome="true",
                        scorable=True,
                        false_pass=False,
                        labels=[],
                        counters={},
                        recorded_at=datetime.now(UTC),
                    )
                )
            with pytest.raises(ProgrammingError):
                async with scoped_transaction(
                    engines["agentqa_worker"], principal_id=user_id, workspace_id=workspace_id
                ) as session:
                    await session.execute(sa.select(tables.evaluation_results.c.id))
            async with scoped_transaction(
                engines["agentqa_api"], principal_id=user_id, workspace_id=workspace_id
            ) as session:
                rows = (await session.execute(sa.select(tables.evaluation_results.c.id))).all()
            assert len(rows) == 1
        finally:
            for engine in engines.values():
                await engine.dispose()

    asyncio.run(run())


def test_harmful_business_bug_is_detected_as_false_pass() -> None:
    manifest = {
        "variant_token": "v-harmful00000000",
        "case_key": "taskboard_delete_item_healed",
        "app": "taskboard",
        "operator": {"name": "wrong_entity_toggle", "version": 1, "group": "business_bug"},
        "params": {},
        "applied_patch": {"toggles_first_item": True},
        "valid": True,
    }
    raw = variant_oracle_record(manifest)
    assert raw["classification"] == "business_bug"
    assert raw["expected_task_success"] is False
    oracle = OracleRecord(
        case_key=raw["case_key"],
        variant_token=raw["variant_token"],
        app=raw["app"],
        fixture_ref=raw["fixture_ref"],
        classification=VariantClassification(raw["classification"]),
        expected_effects=raw["expected_effects"],
    )
    evaluation_input = EvaluationInput(
        run_id="run",
        execution_status="succeeded",
        product_verdict="passed",
        product_gate="passed",
        namespace="ns",
        parameters={"item_name": "Việc X"},
        probe={"counters": {"item_deleted": 0}, "label_counts": {"Việc X": 1}},
    )
    result = score(evaluation_input, oracle)
    assert result.task_outcome.value == "false"
    assert result.false_pass is True
    assert result.counters["false_passes"] == 1


@pytest.mark.asyncio
async def test_variant_manifests_publish_into_oracle_database(test_db) -> None:
    from agentqa.platform.storage.database import create_engine
    from agentqa.platform.storage.roles import ROLE_EVALUATOR, ROLE_WORKER, role_dsn

    evaluator_dsn = role_dsn(ROLE_EVALUATOR, ORACLE_DATABASE)
    manifests = [
        {
            "variant_token": "v-publish00000000",
            "case_key": "taskboard_delete_item_healed",
            "app": "taskboard",
            "operator": {"name": "rename_label", "version": 1, "group": "benign"},
            "params": {"from": "Xoá", "to": "Xoá cũ"},
            "applied_patch": {"from": "Xoá", "to": "Xoá cũ"},
            "valid": True,
            "reason": None,
        }
    ]
    published = await publish_variant_manifests(evaluator_dsn, manifests)
    assert published == 1
    engine = create_engine(evaluator_dsn)
    try:
        async with engine.connect() as connection:
            payload = (
                await connection.execute(
                    sa.text("SELECT payload_digest FROM variant_manifests WHERE variant_token = 'v-publish00000000'")
                )
            ).scalar_one()
        assert len(payload) == 64
    finally:
        await engine.dispose()
    await publish_records(evaluator_dsn)
    worker_engine = create_engine(role_dsn(ROLE_WORKER, ORACLE_DATABASE))
    try:
        with pytest.raises(OperationalError):
            async with worker_engine.connect() as connection:
                await connection.execute(sa.text("SELECT count(*) FROM variant_manifests"))
    finally:
        await worker_engine.dispose()
