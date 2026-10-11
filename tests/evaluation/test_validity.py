from __future__ import annotations

from agentqa.platform.experiments import generate_variant
from agentqa.platform.fixtures import TaskboardFixture
from tests.support.taskboard import TaskboardServer


def _generate(server: TaskboardServer, namespace: str, group: str, params: dict):
    return generate_variant(
        app="taskboard",
        base_url=server.base_url,
        control_token=server.control_token,
        control_header="x-taskboard-control",
        namespace=namespace,
        fixture_ref="taskboard@1",
        case_key="taskboard_delete_item_healed",
        group=group,
        params=params,
    )


def test_non_applied_rename_is_invalid_with_reason(taskboard_server: TaskboardServer) -> None:
    fixture = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    namespace = "validity-unknown"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = _generate(taskboard_server, namespace, "benign", {"from": "Nhãn không tồn tại", "to": "Nhãn mới"})
    assert outcome.valid is False
    assert outcome.reason == "unknown_label"
    assert outcome.snapshot is None
    assert outcome.manifest is not None
    assert outcome.manifest["valid"] is False
    assert outcome.manifest["applied_patch"] == {}


def test_equivalent_rename_is_invalid_with_reason(taskboard_server: TaskboardServer) -> None:
    fixture = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    namespace = "validity-equivalent"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = _generate(taskboard_server, namespace, "benign", {"from": "Xoá", "to": "Xoá"})
    assert outcome.valid is False
    assert outcome.reason == "equivalent_label"
    assert outcome.snapshot is None


def test_invalid_delay_is_rejected(taskboard_server: TaskboardServer) -> None:
    fixture = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    namespace = "validity-delay"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = _generate(taskboard_server, namespace, "temporal", {"seconds": 0})
    assert outcome.valid is False
    assert outcome.reason == "invalid_delay"


def test_duplicate_unknown_label_is_invalid(taskboard_server: TaskboardServer) -> None:
    fixture = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    namespace = "validity-duplicate"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = _generate(taskboard_server, namespace, "distractor", {"label": "Không tồn tại"})
    assert outcome.valid is False
    assert outcome.reason == "unknown_label"


def test_valid_variant_has_blind_token_without_descriptive_fields(taskboard_server: TaskboardServer) -> None:
    fixture = TaskboardFixture(taskboard_server.base_url, taskboard_server.control_token)
    namespace = "validity-valid"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = _generate(taskboard_server, namespace, "benign", {"from": "Xoá", "to": "Xoá cũ"})
    assert outcome.valid is True
    assert outcome.snapshot is not None
    assert "operator" not in outcome.snapshot
    assert "classification" not in outcome.snapshot
    assert outcome.manifest is not None and outcome.manifest["applied_patch"]
