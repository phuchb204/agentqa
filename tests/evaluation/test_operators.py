from __future__ import annotations

import json
from pathlib import Path

from agentqa.platform.experiments import (
    GROUP_OPERATOR,
    OPERATORS,
    generate_variant,
    snapshot_digest,
    write_public_snapshot,
)
from agentqa.platform.fixtures import CanvasdeskFixture, ShopflowFixture, TaskboardFixture
from tests.support.canvasdesk import CanvasdeskServer
from tests.support.shopflow import ShopflowServer
from tests.support.taskboard import TaskboardServer

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_TOKEN_KEYS = {"schema_version", "variant_token", "app", "fixture_ref", "build_digest"}

APP_SETUPS = {
    "taskboard": {"seed": "wrong_entity"},
    "shopflow": {"seed": "catalog_default"},
    "canvasdesk": {"seed": "default"},
}
CONTROL_HEADERS = {
    "taskboard": "x-taskboard-control",
    "shopflow": "x-shopflow-control",
    "canvasdesk": "x-canvasdesk-control",
}


def _fixture(server, app: str):
    builders = {
        "taskboard": lambda: TaskboardFixture(server.base_url, server.control_token),
        "shopflow": lambda: ShopflowFixture(server.base_url, server.control_token),
        "canvasdesk": lambda: CanvasdeskFixture(server.base_url, server.control_token),
    }
    return builders[app]()


def test_operator_matrix_covers_four_groups_for_every_app() -> None:
    groups = {"benign", "distractor", "business_bug", "temporal"}
    for app in ("taskboard", "shopflow", "canvasdesk"):
        assert {group for (candidate, group) in GROUP_OPERATOR if candidate == app} == groups


def test_variants_apply_and_verify_for_every_group(
    taskboard_server: TaskboardServer, shopflow_server: ShopflowServer, canvasdesk_server: CanvasdeskServer
) -> None:
    servers = {
        "taskboard": taskboard_server,
        "shopflow": shopflow_server,
        "canvasdesk": canvasdesk_server,
    }
    for app, server in servers.items():
        fixture = _fixture(server, app)
        for group in ("benign", "distractor", "business_bug", "temporal"):
            namespace = f"variant-{app}-{group}"
            assert fixture.prepare(namespace, seed=APP_SETUPS[app]["seed"]).ok
            outcome = generate_variant(
                app=app,
                base_url=server.base_url,
                control_token=server.control_token,
                control_header=CONTROL_HEADERS[app],
                namespace=namespace,
                fixture_ref=f"{app}@1",
                case_key="taskboard_delete_item_healed" if app == "taskboard" else "shopflow_search_filter",
                group=group,
            )
            assert outcome.valid, (app, group, outcome.reason)
            assert outcome.group == group
            assert outcome.manifest is not None
            manifest = outcome.manifest
            assert manifest["operator"]["group"] == group
            assert manifest["operator"]["version"] >= 1
            assert manifest["applied_patch"], (app, group)
            assert manifest["build_before"] != manifest["build_after"]
            assert manifest["valid"] is True
            assert manifest["reason"] is None
            if group == "business_bug":
                assert manifest["classification"]["expected_task_success"] is False
            else:
                assert manifest["classification"]["expected_task_success"] is True


def test_public_snapshot_is_blind_token_and_written_under_public_tokens(
    taskboard_server: TaskboardServer,
) -> None:
    fixture = _fixture(taskboard_server, "taskboard")
    namespace = "variant-blind"
    assert fixture.prepare(namespace, seed="wrong_entity").ok
    outcome = generate_variant(
        app="taskboard",
        base_url=taskboard_server.base_url,
        control_token=taskboard_server.control_token,
        control_header=CONTROL_HEADERS["taskboard"],
        namespace=namespace,
        fixture_ref="taskboard@1",
        case_key="taskboard_delete_item_healed",
        group="benign",
    )
    assert outcome.valid and outcome.snapshot is not None
    snapshot = outcome.snapshot
    assert set(snapshot) == PUBLIC_TOKEN_KEYS
    text = json.dumps(snapshot, ensure_ascii=False)
    for leak in ("rename_label", "benign", "operator", "Xoá cũ", "expected", "patch"):
        assert leak not in text, leak
    path = write_public_snapshot(REPO_ROOT, snapshot)
    assert path.is_file()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == snapshot
    assert len(snapshot_digest(snapshot)) == 64


def test_operator_registry_is_versioned() -> None:
    for spec in OPERATORS.values():
        assert spec.version >= 1
        assert spec.group in {"benign", "distractor", "business_bug", "temporal"}
        assert spec.apps
