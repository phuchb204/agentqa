from __future__ import annotations

import hashlib
import time
from pathlib import Path

import yaml
from tests.support.taskboard import TaskboardServer, alice_session, load_scenario

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import CheckpointNode
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.values import LiteralValue
from agentqa.platform.fixtures import TASKBOARD_FIXTURE, FixtureRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = REPO_ROOT / "benchmarks" / "public" / "cases" / "taskboard"
FIXTURE_MANIFEST = REPO_ROOT / "benchmarks" / "public" / "fixtures" / "taskboard.yaml"


def expected_count(compiled, assertion_id: str) -> int:
    for node in compiled.case.nodes:
        if isinstance(node, CheckpointNode):
            for assertion in node.assertions:
                if assertion.id == assertion_id:
                    expected = assertion.expected
                    assert isinstance(expected, LiteralValue)
                    value = expected.value
                    assert isinstance(value, int)
                    return value
    raise AssertionError(f"assertion {assertion_id} không tồn tại")


def test_registry_lifecycle_prepare_reset_probe_cleanup(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    namespace = "registry-lifecycle"
    receipt = fixture_registry.prepare("taskboard@1", namespace)
    assert receipt.ok
    assert receipt.fixture_ref == "taskboard@1"
    assert "fixture_digest" in (receipt.detail or "")
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["item_count"] == 0
    http = alice_session(taskboard_server.base_url, namespace)
    http.create_item(namespace, "Việc tạm")
    assert fixture_registry.probe("taskboard@1", namespace)["item_count"] == 1
    reset = fixture_registry.reset("taskboard@1", namespace)
    assert reset.ok
    after_reset = fixture_registry.probe("taskboard@1", namespace)
    assert after_reset["item_count"] == 0
    assert after_reset["counters"].get("item_created", 0) == 0
    cleanup = fixture_registry.cleanup("taskboard@1", namespace)
    assert cleanup.ok
    assert "true" in (cleanup.detail or "")


def test_registry_unknown_fixture_and_wrong_version(fixture_registry: FixtureRegistry) -> None:
    missing = fixture_registry.prepare("khong-ton-tai", "namespace-x")
    assert not missing.ok
    registered = fixture_registry.definition("taskboard@1")
    assert registered is not None
    assert registered.ref() == "taskboard@1"
    wrong_version = fixture_registry.prepare("taskboard@9", "namespace-x")
    assert not wrong_version.ok
    assert fixture_registry.definition("taskboard@9") is None


def test_namespace_per_execution_attempt_isolated(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    namespace_one = "exec-7-attempt-1"
    namespace_two = "exec-7-attempt-2"
    assert fixture_registry.prepare("taskboard@1", namespace_one).ok
    assert fixture_registry.prepare("taskboard@1", namespace_two).ok
    http = alice_session(taskboard_server.base_url, namespace_one)
    http.create_item(namespace_one, "Chỉ thuộc attempt 1")
    probe_one = fixture_registry.probe("taskboard@1", namespace_one)
    probe_two = fixture_registry.probe("taskboard@1", namespace_two)
    assert probe_one["label_counts"]["Chỉ thuộc attempt 1"] == 1
    assert "Chỉ thuộc attempt 1" not in probe_two["label_counts"]
    assert probe_two["item_count"] == 0
    assert probe_two["counters"].get("item_created", 0) == 0


def test_side_effect_counter_counts_retries_and_actual_target(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario = load_scenario("scenario_wrong_entity")
    namespace = "sensor-count"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario["seed"]).ok
    http = alice_session(taskboard_server.base_url, namespace)
    http.create_item(namespace, "Việc giống nhau")
    http.create_item(namespace, "Việc giống nhau")
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["counters"].get("item_created") == 2
    assert probe["label_counts"]["Việc giống nhau"] == 4
    http.delete_item(namespace, "item-2")
    after_delete = fixture_registry.probe("taskboard@1", namespace)
    assert after_delete["last_write_target"]["kind"] == "item_deleted"
    assert after_delete["last_write_target"]["entity_id"] == "item-2"
    assert after_delete["item_count"] == 3


def test_manifest_digest_matches_definition(fixture_registry: FixtureRegistry) -> None:
    manifest = yaml.safe_load(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest) == {"fixture_id", "version", "seeds"}
    assert digest_content(manifest) == TASKBOARD_FIXTURE.digest()
    definition = fixture_registry.definition("taskboard@1")
    assert definition is not None
    assert definition.ref() == "taskboard@1"
    assert definition.digest() == TASKBOARD_FIXTURE.digest()
    assert definition.digest() == definition.digest()


def test_cases_compile_with_verified_sources() -> None:
    source_text = (CASE_DIR / "source.md").read_text(encoding="utf-8")
    source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    quotes = yaml.safe_load((CASE_DIR / "quotes.yaml").read_text(encoding="utf-8"))
    case_paths = sorted(path for path in CASE_DIR.glob("*.yaml") if path.name != "quotes.yaml")
    assert len(case_paths) == 5
    for path in case_paths:
        text = path.read_text(encoding="utf-8")
        compiled = compile_case_document(text)
        again = compile_case_document(text)
        assert compiled.content_digest == again.content_digest
        assert compiled.case.fixture_refs == ["taskboard@1"]
        assert compiled.case.source_defs
        for name, source in compiled.case.source_defs.items():
            assert source.source_content_digest == source_digest
            assert source.quote_digest == hashlib.sha256(quotes[name].encode("utf-8")).hexdigest()
            assert quotes[name] in source_text
            assert f"## {source.anchor.value}" in source_text


def test_success_case_expected_outcome_confirmed_by_probe(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario = load_scenario("scenario_success")
    namespace = "case-success"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario["seed"]).ok
    compiled = compile_case_document((CASE_DIR / "login_create_item.yaml").read_text(encoding="utf-8"))
    expected = expected_count(compiled, "item_exists_once")
    http = alice_session(taskboard_server.base_url, namespace)
    http.create_item(namespace, scenario["item_name"])
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["label_counts"][scenario["item_name"]] == expected
    assert probe["counters"].get("item_created") == expected


def test_business_failure_case_expected_outcome_confirmed_by_probe(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario = load_scenario("scenario_duplicate")
    namespace = "case-duplicate"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario["seed"]).ok
    compiled = compile_case_document((CASE_DIR / "duplicate_label_rejected.yaml").read_text(encoding="utf-8"))
    expected = expected_count(compiled, "duplicate_not_created")
    http = alice_session(taskboard_server.base_url, namespace)
    response = http.create_item(namespace, scenario["item_name"])
    assert "đã tồn tại" in response.text
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["label_counts"][scenario["item_name"]] == expected
    assert probe["counters"].get("duplicate_rejected") == 1
    assert probe["counters"].get("item_created", 0) == 0


def test_async_unknown_case_probe_transitions_pending_to_settled(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario = load_scenario("scenario_async")
    namespace = "case-async"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario["seed"]).ok
    compiled = compile_case_document((CASE_DIR / "async_create_unknown.yaml").read_text(encoding="utf-8"))
    expected = expected_count(compiled, "item_exists_once")
    http = alice_session(taskboard_server.base_url, namespace)
    response = http.create_async(namespace, scenario["item_name"])
    assert "Đang xử lý" in response.text
    pending = fixture_registry.probe("taskboard@1", namespace)
    assert pending["jobs"]
    assert all(job["status"] == "pending" for job in pending["jobs"].values())
    assert pending["counters"].get("async_settled", 0) == 0
    deadline = time.monotonic() + 8.0
    settled = fixture_registry.probe("taskboard@1", namespace)
    while time.monotonic() < deadline and settled["counters"].get("async_settled", 0) == 0:
        time.sleep(0.1)
        settled = fixture_registry.probe("taskboard@1", namespace)
    assert settled["counters"].get("async_settled") == 1
    assert settled["label_counts"][scenario["item_name"]] == expected
    assert all(job["status"] == "succeeded" for job in settled["jobs"].values())
