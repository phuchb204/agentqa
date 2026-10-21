from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from oracle.registry import RECORDS, registry_digest, stable_opportunity_id

__all__ = ["stable_opportunity_id"]

OPERATOR_GROUP = {
    "rename_label": "benign",
    "duplicate_label": "distractor",
    "duplicate_product_ref": "distractor",
    "wrong_entity_toggle": "business_bug",
    "drop_qty_effect": "business_bug",
    "drop_theme_effect": "business_bug",
    "delay_settle": "temporal",
    "delay_render": "temporal",
}

CREATE_VARIANTS = sa.text(
    """
    CREATE TABLE IF NOT EXISTS variant_manifests (
        variant_token text PRIMARY KEY,
        app text NOT NULL,
        case_key text NOT NULL,
        operator text NOT NULL,
        valid boolean NOT NULL,
        reason text,
        payload jsonb NOT NULL,
        payload_digest text NOT NULL,
        registry_digest text NOT NULL,
        published_at timestamptz NOT NULL DEFAULT now()
    )
    """
)

UPSERT_VARIANT = sa.text(
    """
    INSERT INTO variant_manifests (
        variant_token, app, case_key, operator, valid, reason, payload, payload_digest, registry_digest
    )
    VALUES (
        :variant_token, :app, :case_key, :operator, :valid, :reason,
        CAST(:payload AS jsonb), :payload_digest, :registry_digest
    )
    ON CONFLICT (variant_token) DO UPDATE SET
        app = EXCLUDED.app,
        case_key = EXCLUDED.case_key,
        operator = EXCLUDED.operator,
        valid = EXCLUDED.valid,
        reason = EXCLUDED.reason,
        payload = EXCLUDED.payload,
        payload_digest = EXCLUDED.payload_digest,
        registry_digest = EXCLUDED.registry_digest,
        published_at = now()
    """
)


def opportunities_for(
    case_key: str, operator: str, params: dict[str, Any], patch: dict[str, Any]
) -> list[dict[str, Any]]:
    if case_key == "taskboard_delete_item_healed" and operator == "rename_label":
        return [
            {
                "opportunity_id": stable_opportunity_id("delete_item", "delete_item", "Xoá việc"),
                "step_id": "delete_item",
                "original_identity": "delete_item:Xoá việc",
                "expected_identity": None,
                "expected_entity": "item-1",
                "kind": "benign_mismatch",
            }
        ]
    if operator == "duplicate_label":
        if case_key == "taskboard_delete_item_healed":
            return [
                {
                    "opportunity_id": stable_opportunity_id("delete_item", "delete_item", "Xoá việc"),
                    "step_id": "delete_item",
                    "original_identity": "delete_item:Xoá việc",
                    "expected_identity": None,
                    "expected_entity": None,
                    "kind": "ambiguous_target",
                }
            ]
        return [
            {
                "opportunity_id": stable_opportunity_id("add_duplicate", "create_item", "Thêm việc"),
                "step_id": "add_duplicate",
                "original_identity": "create_item:Thêm việc",
                "expected_identity": None,
                "expected_entity": None,
                "kind": "ambiguous_target",
            }
        ]
    if case_key == "canvasdesk_hotspot_select" and operator == "rename_label":
        return [
            {
                "opportunity_id": stable_opportunity_id("select_hotspot_b", "hotspot_b", "Ô B"),
                "step_id": "select_hotspot_b",
                "original_identity": "hotspot_b:Ô B",
                "expected_identity": None,
                "expected_entity": None,
                "kind": "ambiguous_target",
            }
        ]
    if case_key == "shopflow_cart_checkout_async" and operator == "rename_label":
        return [
            {
                "opportunity_id": stable_opportunity_id("add_product", "add_to_cart", "Thêm Ly thuỷ tinh vào giỏ"),
                "step_id": "add_product",
                "original_identity": "add_to_cart:Thêm Ly thuỷ tinh vào giỏ",
                "expected_identity": None,
                "expected_entity": None,
                "kind": "ambiguous_target",
            }
        ]
    return []


def variant_oracle_record(manifest: dict[str, Any]) -> dict[str, Any]:
    case_key = str(manifest["case_key"])
    base = RECORDS.get(case_key)
    if base is None:
        raise KeyError(f"không có oracle record cho case '{case_key}'")
    operator = str(manifest["operator"]["name"])
    params = dict(manifest.get("params", {}))
    patch = dict(manifest.get("applied_patch", {}))
    group = OPERATOR_GROUP.get(operator, "benign")
    return {
        "case_key": case_key,
        "variant_token": manifest.get("variant_token"),
        "app": base["app"],
        "fixture_ref": base["fixture_ref"],
        "classification": group,
        "expected_task_success": group != "business_bug",
        "expected_effects": list(base["expected_effects"]),
        "opportunities": opportunities_for(case_key, operator, params, patch),
        "oracle_task_success": base.get("oracle_task_success", "all_effects"),
    }


async def publish_variant_manifests(dsn: str, manifests: list[dict[str, Any]]) -> int:
    registry_digest_value = registry_digest()
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(CREATE_VARIANTS)
            for manifest in manifests:
                payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
                await connection.execute(
                    UPSERT_VARIANT,
                    {
                        "variant_token": manifest["variant_token"],
                        "app": manifest["app"],
                        "case_key": manifest["case_key"],
                        "operator": manifest["operator"]["name"],
                        "valid": bool(manifest.get("valid", False)),
                        "reason": manifest.get("reason"),
                        "payload": payload,
                        "payload_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                        "registry_digest": registry_digest_value,
                    },
                )
    finally:
        await engine.dispose()
    return len(manifests)
