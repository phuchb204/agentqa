from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.experiments import ExperimentManifest
from agentqa.platform.storage.roles import ROLE_API, ROLE_EVALUATOR, ROLE_MIGRATE, ROLE_SUPERVISOR, ROLE_WORKER
from tests.support.postgres import test_db as test_db

__all__ = ["test_db"]

HARNESS_ROLES = (ROLE_MIGRATE, ROLE_API, ROLE_WORKER, ROLE_SUPERVISOR, ROLE_EVALUATOR)


@pytest_asyncio.fixture(name="role_engines")
async def role_engines_fixture(test_db) -> AsyncIterator[dict]:
    engines = {role: create_async_engine(test_db.dsn(role), pool_size=5, max_overflow=5) for role in HARNESS_ROLES}
    yield engines
    for engine in engines.values():
        await engine.dispose()


def minimal_manifest(**overrides) -> dict:
    content = {
        "schema_version": "experiment-manifest/1",
        "experiment_id": "unit-experiment",
        "version": "1",
        "research_question": "rq3",
        "corpus": {"cases": ["taskboard_create_item", "taskboard_delete_item_healed"], "data_rows": []},
        "arms": [
            {"arm_id": "static_baseline", "mode": "replay", "policy": "replay_strict"},
            {"arm_id": "llm_agent", "mode": "agent", "policy": "llm", "observation": "hybrid"},
            {"arm_id": "cascade_agent", "mode": "agent", "policy": "jev_cascade"},
            {"arm_id": "strict_replay", "mode": "replay", "policy": "replay_strict"},
            {"arm_id": "healing_replay", "mode": "replay", "policy": "replay_healing", "healing": True},
        ],
        "samples": {"unit": "case_family", "confidence": 0.95, "repetitions": 1},
        "budgets": {
            "max_calls": 10,
            "max_cost_usd": 1.0,
            "routes": {"opencode_go": "deepseek-v4.1-flash", "opencode_zen": "jev-1.13-free"},
        },
        "analysis": {
            "primary_endpoints": ["oracle_task_success"],
            "comparisons": [["llm_agent", "static_baseline"]],
            "bootstrap_seed": 7,
            "bootstrap_replicates": 500,
            "multiple_comparison": "holm",
        },
        "seeds": [7],
    }
    content.update(overrides)
    return content


def slot_payload(
    *,
    arm_id: str,
    case_key: str,
    status: str = "completed",
    task_outcome: str = "true",
    product_passed: bool = True,
    false_heals: int = 0,
    correct_heals: int = 0,
    refusals: int = 0,
    detected: int = 0,
    missed: int = 0,
    model_requested: str | None = None,
    model_resolved: str | None = None,
    provider_cache: bool = False,
    cost_basis: str | None = None,
    wall_time: float = 1.0,
) -> dict:
    payload = {
        "product": {"verdict": "passed" if product_passed else "failed", "gate": "passed"},
        "oracle": {
            "task_outcome": task_outcome,
            "false_pass": product_passed and task_outcome == "false",
            "counters": {
                "detected": detected,
                "missed": missed,
                "attempts_total": correct_heals + false_heals + refusals,
                "correct_heals": correct_heals,
                "false_heals": false_heals,
                "refusals": refusals,
            },
        },
        "gate": {"result": "passed"},
        "usage": {"calls": 1, "input_tokens": 10, "output_tokens": 5, "wall_time_seconds": wall_time},
    }
    if model_requested:
        payload["model_requested"] = model_requested
        payload["model_resolved"] = model_resolved
    if provider_cache:
        payload["provider_cache_observed"] = True
    if cost_basis:
        payload["cost_basis"] = cost_basis
    return {
        "slot_key": f"{arm_id}|{case_key}",
        "arm_id": arm_id,
        "case_key": case_key,
        "variant_token": None,
        "data_row": None,
        "repetition": 1,
        "attempt_no": 1,
        "status": status,
        "blocked_reason": "capability_missing" if status == "blocked" else None,
        "payload": payload,
    }


def manifest_from(content: dict) -> ExperimentManifest:
    return ExperimentManifest.model_validate(content)
