from __future__ import annotations

import hashlib
from typing import Any

from agentqa.contracts.canonical import digest_content

ORACLE_VERSION = 1

SHOPFLOW_CANDIDATE_IDS = tuple(
    f"{prefix}-{index}" for prefix in ("line", "order", "job", "upload") for index in range(1, 21)
)
CANVASDESK_CANDIDATE_IDS = tuple(f"cell-{index}" for index in range(1, 5))


def _opaque(prefix: str, namespace: str, entity_id: str) -> str:
    material = f"{prefix}:{namespace}:{entity_id}".encode()
    return ("sf-" if prefix == "shopflow" else "cd-") + hashlib.sha256(material).hexdigest()[:16]


def resolve_ref(app: str, namespace: str, ref: str) -> str | None:
    if app == "shopflow":
        candidates = SHOPFLOW_CANDIDATE_IDS
        prefix = "shopflow"
    elif app == "canvasdesk":
        candidates = CANVASDESK_CANDIDATE_IDS
        prefix = "canvasdesk"
    else:
        return None
    return next((entity_id for entity_id in candidates if _opaque(prefix, namespace, entity_id) == ref), None)


def _effect(kind: str, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, **fields}


def stable_opportunity_id(node: str, intent: str, name: str | None) -> str:
    material = digest_content({"node": node, "intent": intent, "name": name})
    return f"opp-{material[:16]}"


RECORDS: dict[str, dict[str, Any]] = {
    "taskboard_create_item": {
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "expected_effects": [
            _effect("counter_equals", counter="item_created", value=1),
            _effect("label_count_equals", parameter="item_name", value=1),
        ],
        "oracle_task_success": "all_effects",
    },
    "taskboard_duplicate_label_rejected": {
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "expected_effects": [
            _effect("counter_equals", counter="duplicate_rejected", value=1),
            _effect("counter_equals", counter="item_created", value=0),
        ],
        "oracle_task_success": "all_effects",
    },
    "taskboard_async_create_unknown": {
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "expected_effects": [
            _effect("counter_equals", counter="async_settled", value=1),
            _effect("label_count_equals", parameter="item_name", value=1),
        ],
        "oracle_task_success": "all_effects",
    },
    "taskboard_delete_item_healed": {
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "expected_effects": [
            _effect("counter_equals", counter="item_deleted", value=1),
            _effect("label_count_equals", parameter="item_name", value=0),
        ],
        "opportunities": [
            {
                "opportunity_id": stable_opportunity_id("delete_item", "delete_item", "Xoá việc"),
                "step_id": "delete_item",
                "original_identity": "delete_item:Xoá việc",
                "expected_identity": None,
                "expected_entity": "item-1",
                "kind": "benign_mismatch",
            }
        ],
        "oracle_task_success": "all_effects",
    },
    "taskboard_evidence_locator_healed": {
        "app": "taskboard",
        "fixture_ref": "taskboard@1",
        "expected_effects": [
            _effect("counter_equals", counter="item_created", value=1),
            _effect("label_count_equals", parameter="item_name", value=1),
        ],
        "oracle_task_success": "all_effects",
    },
    "shopflow_search_filter": {
        "app": "shopflow",
        "fixture_ref": "shopflow@1",
        "expected_effects": [
            _effect("counter_at_least", counter="search_performed", value=1),
            _effect("counter_equals", counter="cart_line_added", value=0),
        ],
        "oracle_task_success": "all_effects",
    },
    "shopflow_cart_checkout_async": {
        "app": "shopflow",
        "fixture_ref": "shopflow@1",
        "expected_effects": [
            _effect("counter_equals", counter="cart_line_added", value=1),
            _effect("counter_equals", counter="cart_qty_changed", value=1),
            _effect("counter_equals", counter="checkout_settled", value=1),
            _effect("order_count_equals", value=1),
            _effect("cart_line_count_equals", value=0),
        ],
        "oracle_task_success": "all_effects",
    },
    "shopflow_stock_rejected": {
        "app": "shopflow",
        "fixture_ref": "shopflow@1",
        "expected_effects": [
            _effect("counter_at_least", counter="cart_rejected", value=1),
            _effect("counter_equals", counter="cart_line_added", value=0),
            _effect("counter_equals", counter="checkout_rejected", value=1),
            _effect("cart_line_count_equals", value=0),
        ],
        "oracle_task_success": "all_effects",
    },
    "shopflow_upload_download_lab": {
        "app": "shopflow",
        "fixture_ref": "shopflow@1",
        "expected_effects": [
            _effect("counter_equals", counter="upload_received", value=1),
            _effect("counter_equals", counter="download_served", value=1),
        ],
        "oracle_task_success": "all_effects",
    },
    "canvasdesk_hotspot_select": {
        "app": "canvasdesk",
        "fixture_ref": "canvasdesk@1",
        "expected_effects": [
            _effect("counter_equals", counter="hotspot_selected", value=1),
            _effect("resolved_target_equals", ref_field="selected_ref", expected_entity="cell-2"),
        ],
        "oracle_task_success": "all_effects",
    },
    "canvasdesk_theme_visual": {
        "app": "canvasdesk",
        "fixture_ref": "canvasdesk@1",
        "expected_effects": [
            _effect("counter_equals", counter="theme_toggled", value=1),
            _effect("field_equals", field="theme", value="dark"),
        ],
        "oracle_task_success": "all_effects",
    },
    "canvasdesk_scroll_reveal": {
        "app": "canvasdesk",
        "fixture_ref": "canvasdesk@1",
        "expected_effects": [
            _effect("counter_equals", counter="layout_confirmed", value=1),
            _effect("field_equals", field="layout_confirmed", value=True),
        ],
        "oracle_task_success": "all_effects",
    },
    "canvasdesk_delayed_render": {
        "app": "canvasdesk",
        "fixture_ref": "canvasdesk@1",
        "expected_effects": [
            _effect("counter_equals", counter="delayed_rendered", value=1),
            _effect("field_equals", field="delayed_rendered", value=True),
        ],
        "oracle_task_success": "all_effects",
    },
}


def registry_records() -> dict[str, Any]:
    return {
        "version": ORACLE_VERSION,
        "records": {key: RECORDS[key] for key in sorted(RECORDS)},
    }


def registry_digest() -> str:
    return digest_content(registry_records())


def record_for(logical_key: str) -> dict[str, Any] | None:
    return RECORDS.get(logical_key)
