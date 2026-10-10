from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from agentqa.contracts.canonical import digest_content
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER
from tests.support.postgres import scoped_transaction
from tests.support.security import csrf_headers

pytestmark = pytest.mark.asyncio


async def _seed_run(
    runtime,
    workspace_id: str,
    *,
    status: str,
    verdict: str | None,
    gate: str | None,
    reasons: list[str],
    policy: str,
    case_key: str,
    assertions: list[dict],
    usage_settled: int,
    usage_unknown: int,
    environment_revision_id: UUID | None = None,
) -> UUID:
    run_id = uuid4()
    execution_id = uuid4()
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        await session.execute(
            sa.insert(tables.runs).values(
                id=run_id,
                workspace_id=UUID(workspace_id),
                status=status,
                verdict=verdict,
                gate=gate,
                reasons=reasons,
                finalized_at=datetime.now(UTC),
            )
        )
        await session.execute(
            sa.insert(tables.run_snapshots).values(
                workspace_id=UUID(workspace_id),
                run_id=run_id,
                snapshot_version=1,
                content={
                    "policy": policy,
                    "observation_mode": "semantic",
                    "gate_profile": "strict",
                    "cache_profile": "default",
                    "calibration_ref": None,
                    "budgets": {},
                    "content_digests": [digest_content({"case": case_key})],
                    "environment_revision": str(environment_revision_id) if environment_revision_id else None,
                },
                content_digest=digest_content({"run": str(run_id)}),
            )
        )
        await session.execute(
            sa.insert(tables.executions).values(
                id=execution_id,
                workspace_id=UUID(workspace_id),
                run_id=run_id,
                logical_key=case_key,
                status=status,
                verdict=verdict,
            )
        )
    async with scoped_transaction(
        runtime.engines[ROLE_WORKER], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        for assertion in assertions:
            await session.execute(
                sa.insert(tables.assertion_results).values(
                    workspace_id=UUID(workspace_id),
                    run_id=run_id,
                    execution_id=execution_id,
                    checkpoint_id=assertion["checkpoint_id"],
                    assertion_id=assertion["assertion_id"],
                    result=assertion["result"],
                    proof_ref=assertion.get("proof_ref"),
                )
            )
        for _ in range(usage_settled):
            await session.execute(
                sa.insert(tables.model_calls).values(
                    workspace_id=UUID(workspace_id),
                    run_id=run_id,
                    execution_id=execution_id,
                    purpose="observe",
                    requested_model="deepseek-v4.1-flash",
                    route="opencode_go",
                    record_state="settled",
                    outcome="succeeded",
                    usage_input=100,
                    usage_output=20,
                    usage_basis="observed",
                    payload_month=datetime.now(UTC).date(),
                )
            )
        for _ in range(usage_unknown):
            await session.execute(
                sa.insert(tables.model_calls).values(
                    workspace_id=UUID(workspace_id),
                    run_id=run_id,
                    execution_id=execution_id,
                    purpose="observe",
                    requested_model="deepseek-v4.1-flash",
                    route="opencode_go",
                    record_state="unknown",
                    payload_month=datetime.now(UTC).date(),
                )
            )
    return run_id


async def test_run_list_filters_cursor_and_counts(api_client, runtime, owner) -> None:
    workspace_id, csrf, _user_id = owner
    healed_run = await _seed_run(
        runtime,
        workspace_id,
        status="succeeded",
        verdict="passed",
        gate="refused",
        reasons=["healed"],
        policy="default",
        case_key="case_healed",
        assertions=[],
        usage_settled=1,
        usage_unknown=0,
    )
    await _seed_run(
        runtime,
        workspace_id,
        status="succeeded",
        verdict="failed",
        gate="refused",
        reasons=[],
        policy="llm",
        case_key="case_failed",
        assertions=[],
        usage_settled=1,
        usage_unknown=0,
    )

    all_runs = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs")
    assert all_runs.status_code == 200, all_runs.text
    body = all_runs.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    healed = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?healed=true")
    assert healed.status_code == 200
    assert [item["run_id"] for item in healed.json()["items"]] == [str(healed_run)]
    assert healed.json()["items"][0]["annotations"] == ["healed"]

    by_case = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?case_logical_key=case_failed")
    assert by_case.status_code == 200
    assert by_case.json()["total"] == 1
    assert by_case.json()["items"][0]["executions"][0]["logical_key"] == "case_failed"

    by_policy = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?policy=llm")
    assert by_policy.json()["total"] == 1

    page1 = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?limit=1")
    assert page1.status_code == 200
    cursor = page1.json()["next_cursor"]
    assert cursor
    page2 = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?limit=1&cursor={cursor}")
    assert page2.status_code == 200
    ids = {page1.json()["items"][0]["run_id"], page2.json()["items"][0]["run_id"]}
    assert len(ids) == 2

    invalid = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs?cursor=not-a-cursor")
    assert invalid.status_code == 422

    other = await api_client.post(
        "/api/v1/workspaces",
        json={"slug": f"other-{uuid4().hex[:8]}", "name": "other"},
        headers=csrf_headers(csrf),
    )
    scoped = await api_client.get(f"/api/v1/workspaces/{other.json()['id']}/runs")
    assert scoped.status_code == 200
    assert scoped.json()["total"] == 0


async def test_run_detail_evidence_usage_and_missingness(api_client, runtime, owner) -> None:
    workspace_id, _csrf, _user_id = owner
    run_id = await _seed_run(
        runtime,
        workspace_id,
        status="succeeded",
        verdict="passed",
        gate="accepted",
        reasons=[],
        policy="default",
        case_key="detail_case",
        assertions=[
            {
                "checkpoint_id": "check",
                "assertion_id": "a1",
                "result": "passed",
                "proof_ref": '{"expected": "/start", "observed": "/start", "evidence": "present"}',
            }
        ],
        usage_settled=2,
        usage_unknown=1,
    )
    detail = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/detail")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["verdict"] == "passed"
    assert body["gate"] == "accepted"
    assertion = body["executions"][0]["assertions"][0]
    assert assertion["assertion_id"] == "a1"
    assert assertion["proof"]["expected"] == "/start"
    assert body["usage"]["state"] == "partial"
    assert body["usage"]["input_tokens"] == 200
    assert body["usage"]["unknown_calls"] == 1
    assert body["usage"]["cost_state"] == "unknown"
    assert body["snapshot"]["policy"] == "default"


async def test_run_comparison_config_diff_alignment_and_unknown_money(api_client, runtime, owner) -> None:
    workspace_id, _csrf, _user_id = owner
    run_a = await _seed_run(
        runtime,
        workspace_id,
        status="succeeded",
        verdict="passed",
        gate="accepted",
        reasons=[],
        policy="default",
        case_key="compare_case",
        assertions=[
            {
                "checkpoint_id": "check",
                "assertion_id": "a1",
                "result": "passed",
                "proof_ref": '{"expected": "/start", "observed": "/start", "evidence": "present"}',
            },
            {
                "checkpoint_id": "check",
                "assertion_id": "a2",
                "result": "passed",
                "proof_ref": '{"expected": "1", "observed": "1", "evidence": "present"}',
            },
        ],
        usage_settled=1,
        usage_unknown=0,
    )
    run_b = await _seed_run(
        runtime,
        workspace_id,
        status="failed",
        verdict="failed",
        gate="refused",
        reasons=[],
        policy="llm",
        case_key="compare_case",
        assertions=[
            {
                "checkpoint_id": "check",
                "assertion_id": "a1",
                "result": "failed",
                "proof_ref": '{"expected": "/done", "observed": "/start", "evidence": "present"}',
            }
        ],
        usage_settled=0,
        usage_unknown=1,
    )
    comparison = await api_client.get(f"/api/v1/workspaces/{workspace_id}/runs/{run_a}/comparison?against={run_b}")
    assert comparison.status_code == 200, comparison.text
    body = comparison.json()
    config = {entry["field"]: entry for entry in body["config_diff"]}
    assert config["policy"]["equal"] is False
    assert config["policy"]["a"] == "default"
    assert config["policy"]["b"] == "llm"
    assert config["observation_mode"]["equal"] is True

    alignment = {entry["logical_key"]: entry for entry in body["alignment"]}
    case_alignment = alignment["compare_case"]
    rows = {(row["checkpoint_id"], row["assertion_id"]): row for row in case_alignment["assertions"]}
    assert rows[("check", "a1")]["aligned"] is True
    assert rows[("check", "a1")]["a_expected"] == "/start"
    assert rows[("check", "a1")]["b_expected"] == "/done"
    assert rows[("check", "a2")]["aligned"] is False
    assert rows[("check", "a2")]["b_status"] is None

    assert body["metrics"]["a"]["usage_state"] == "complete"
    assert body["metrics"]["b"]["usage_state"] == "partial"
    assert body["metrics"]["b"]["cost_state"] == "unknown"
    assert body["metrics"]["b"]["usage_input_tokens"] == 0
