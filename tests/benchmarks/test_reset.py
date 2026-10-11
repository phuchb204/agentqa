from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml

from agentqa.platform.fixtures import (
    CANVASDESK_FIXTURE,
    SHOPFLOW_FIXTURE,
    TASKBOARD_FIXTURE,
    CanvasdeskFixture,
    FixtureDefinition,
    ShopflowFixture,
    canvasdesk_password,
    shopflow_password,
)
from tests.support.taskboard import TaskboardServer
from tests.support.taskboard import alice_session as taskboard_session

PUBLIC_ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "public"
FIXTURES_ROOT = PUBLIC_ROOT / "fixtures"

RECIPES: dict[str, FixtureDefinition] = {
    "taskboard": TASKBOARD_FIXTURE,
    "shopflow": SHOPFLOW_FIXTURE,
    "canvasdesk": CANVASDESK_FIXTURE,
}

DEFAULT_SEED = {"taskboard": "success", "shopflow": "catalog_default", "canvasdesk": "default"}


def test_recipes_match_runtime_definitions_with_stable_digests() -> None:
    for fixture_id, definition in RECIPES.items():
        recipe = yaml.safe_load((FIXTURES_ROOT / f"{fixture_id}.yaml").read_text(encoding="utf-8"))
        assert recipe["fixture_id"] == fixture_id
        assert int(recipe["version"]) == definition.version
        assert recipe["seeds"] == definition.seeds, f"{fixture_id} recipe drift so với FixtureDefinition"
        assert definition.default_seed in definition.seeds
        first = definition.digest()
        second = FixtureDefinition(
            fixture_id=definition.fixture_id, version=definition.version, seeds=dict(definition.seeds)
        ).digest()
        assert first == second
        assert len(first) == 64


def _mutate_taskboard(taskboard_server: TaskboardServer, namespace: str) -> None:
    http = taskboard_session(taskboard_server.base_url, namespace)
    http.create_item(namespace, "Việc tạm")


def _mutate_shopflow(shopflow_fixture: ShopflowFixture, namespace: str) -> None:
    with httpx.Client(base_url=shopflow_fixture.base_url, follow_redirects=True, timeout=10.0) as client:
        client.post(
            f"/{namespace}/login",
            data={"username": "alice", "password": shopflow_password(namespace, "alice")},
        )
        client.post(f"/{namespace}/cart/lines", data={"product_id": "sp-1", "qty": 1})


def _mutate_canvasdesk(canvasdesk_fixture: CanvasdeskFixture, namespace: str) -> None:
    with httpx.Client(base_url=canvasdesk_fixture.base_url, follow_redirects=True, timeout=10.0) as client:
        client.post(
            f"/{namespace}/login",
            data={"username": "alice", "password": canvasdesk_password(namespace, "alice")},
        )
        client.post(f"/{namespace}/board/select", data={"cell_id": "cell-1"})


def test_prepare_reset_restores_seed_and_zeroes_counters(
    taskboard_server: TaskboardServer,
    shopflow_fixture: ShopflowFixture,
    canvasdesk_fixture: CanvasdeskFixture,
    benchmark_registry,
) -> None:
    scenarios = [
        ("taskboard@1", "reset-taskboard", lambda ns: _mutate_taskboard(taskboard_server, ns)),
        ("shopflow@1", "reset-shopflow", lambda ns: _mutate_shopflow(shopflow_fixture, ns)),
        ("canvasdesk@1", "reset-canvasdesk", lambda ns: _mutate_canvasdesk(canvasdesk_fixture, ns)),
    ]
    for fixture_ref, namespace, mutate in scenarios:
        fixture_id = fixture_ref.partition("@")[0]
        receipt = benchmark_registry.prepare(fixture_ref, namespace, seed=DEFAULT_SEED[fixture_id])
        assert receipt.ok, receipt.detail
        detail = json.loads(str(receipt.detail))
        assert detail["fixture_digest"] == RECIPES[fixture_id].digest()

        def side_effect_counters(probe: dict) -> dict[str, int]:
            return {kind: value for kind, value in probe["counters"].items() if kind not in ("namespace_prepared",)}

        before = benchmark_registry.probe(fixture_ref, namespace)
        assert before["revision"] == 0
        assert all(value == 0 for value in side_effect_counters(before).values())

        mutate(namespace)
        mutated = benchmark_registry.probe(fixture_ref, namespace)
        assert mutated["revision"] >= 1

        reset_receipt = benchmark_registry.reset(fixture_ref, namespace)
        assert reset_receipt.ok, reset_receipt.detail
        after = benchmark_registry.probe(fixture_ref, namespace)
        assert after["revision"] == 0
        assert all(value == 0 for value in side_effect_counters(after).values())


def test_cleanup_removes_namespace(canvasdesk_fixture: CanvasdeskFixture, benchmark_registry) -> None:
    namespace = "cleanup-canvasdesk"
    assert benchmark_registry.prepare("canvasdesk@1", namespace).ok
    assert benchmark_registry.cleanup("canvasdesk@1", namespace).ok
    with httpx.Client(timeout=5.0) as client:
        response = client.get(
            f"{canvasdesk_fixture.base_url}/_control/namespaces/{namespace}/probe",
            headers={"x-canvasdesk-control": canvasdesk_fixture.control_token},
        )
    assert response.status_code == 404


def test_recipe_digest_is_content_sensitive() -> None:
    definition = RECIPES["shopflow"]
    altered = {**definition.seeds, "catalog_default": {"catalog": []}}
    changed = FixtureDefinition(fixture_id=definition.fixture_id, version=definition.version, seeds=altered)
    assert changed.digest() != definition.digest()
    assert canvasdesk_password("ns", "alice").startswith("cd-")
