from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agentqa.contracts.canonical import digest_content
from agentqa.platform.fixtures import (
    canvasdesk_password,
    shopflow_password,
    synthetic_password,
)

PUBLIC_TOKEN_SCHEMA = "variant-token/1"
MANIFEST_SCHEMA = "variant-manifest/1"


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    group: str
    version: int
    apps: tuple[str, ...]


OPERATORS: dict[str, OperatorSpec] = {
    "rename_label": OperatorSpec(
        name="rename_label", group="benign", version=1, apps=("taskboard", "shopflow", "canvasdesk")
    ),
    "duplicate_label": OperatorSpec(
        name="duplicate_label", group="distractor", version=1, apps=("taskboard", "canvasdesk")
    ),
    "duplicate_product_ref": OperatorSpec(
        name="duplicate_product_ref", group="distractor", version=1, apps=("shopflow",)
    ),
    "wrong_entity_toggle": OperatorSpec(
        name="wrong_entity_toggle", group="business_bug", version=1, apps=("taskboard",)
    ),
    "drop_qty_effect": OperatorSpec(name="drop_qty_effect", group="business_bug", version=1, apps=("shopflow",)),
    "drop_theme_effect": OperatorSpec(name="drop_theme_effect", group="business_bug", version=1, apps=("canvasdesk",)),
    "delay_settle": OperatorSpec(name="delay_settle", group="temporal", version=1, apps=("taskboard", "shopflow")),
    "delay_render": OperatorSpec(name="delay_render", group="temporal", version=1, apps=("canvasdesk",)),
}

GROUP_OPERATOR: dict[tuple[str, str], str] = {
    (app, spec.group): spec.name for spec in OPERATORS.values() for app in spec.apps
}


@dataclass
class VariantOutcome:
    valid: bool
    reason: str | None
    operator: str
    group: str
    snapshot: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None


def operator_for_group(app: str, group: str) -> OperatorSpec:
    name = GROUP_OPERATOR.get((app, group))
    if name is None:
        raise KeyError(f"app '{app}' không có operator cho nhóm '{group}'")
    return OPERATORS[name]


def _login(client: httpx.Client, app: str, namespace: str) -> None:
    passwords = {
        "taskboard": synthetic_password,
        "shopflow": shopflow_password,
        "canvasdesk": canvasdesk_password,
    }
    response = client.post(
        f"/{namespace}/login",
        data={"username": "alice", "password": passwords[app](namespace, "alice")},
    )
    response.raise_for_status()


def _verify_rendered(
    app: str, namespace: str, operator: str, params: dict[str, Any], patch: dict[str, Any], base_url: str
) -> tuple[bool, str | None]:
    with httpx.Client(base_url=base_url, follow_redirects=True, timeout=10.0) as client:
        _login(client, app, namespace)
        if app == "taskboard":
            html = client.get(f"/{namespace}/tasks").text
            if operator == "rename_label":
                applied = f">{patch.get('to')}<" in html and ">Xoá<" not in html
                return (applied, None if applied else "effect_not_rendered")
            if operator == "duplicate_label":
                label = str(patch.get("label", ""))
                applied = html.count(f'<span class="item-label">{label}</span>') >= 2
                return (applied, None if applied else "effect_not_rendered")
            return True, None
        if app == "shopflow":
            if operator == "rename_label":
                new_rows = client.get(f"/{namespace}/api/search", params={"q": str(patch.get("to", ""))}).json()[
                    "results"
                ]
                old_rows = client.get(f"/{namespace}/api/search", params={"q": str(patch.get("from", ""))}).json()[
                    "results"
                ]
                applied = bool(new_rows) and not old_rows
                return (applied, None if applied else "effect_not_rendered")
            if operator == "duplicate_product_ref":
                rows = client.get(f"/{namespace}/api/search", params={"q": ""}).json()["results"]
                source = str(patch.get("source_product", ""))
                applied = sum(1 for row in rows if row["id"] == source) >= 2
                return (applied, None if applied else "effect_not_rendered")
            return True, None
        if app == "canvasdesk":
            html = client.get(f"/{namespace}/board").text
            if operator == "rename_label":
                applied = f'aria-label="{patch.get("to")}"' in html and f'aria-label="{patch.get("from")}"' not in html
                return (applied, None if applied else "effect_not_rendered")
            if operator == "duplicate_label":
                duplicated = str(patch.get("duplicated", ""))
                applied = html.count(f'aria-label="{duplicated}"') >= 2
                return (applied, None if applied else "effect_not_rendered")
            return True, None
    return False, "unknown_app"


def generate_variant(
    *,
    app: str,
    base_url: str,
    control_token: str,
    control_header: str,
    namespace: str,
    fixture_ref: str,
    case_key: str,
    group: str,
    params: dict[str, Any] | None = None,
    seed: int = 1,
) -> VariantOutcome:
    spec = operator_for_group(app, group)
    payload_params = dict(params or {})
    if spec.name == "rename_label" and "from" not in payload_params:
        defaults = {
            "taskboard": {"from": "Xoá", "to": "Xoá cũ"},
            "shopflow": {"from": "Ly thuỷ tinh", "to": "Ly thủy tinh"},
            "canvasdesk": {"from": "Ô B", "to": "Vùng B"},
        }
        payload_params = defaults[app]
    if spec.name == "duplicate_label" and "label" not in payload_params:
        defaults = {"taskboard": "Việc giống nhau", "canvasdesk": None}
        if defaults.get(app):
            payload_params = {"label": defaults[app]}
    if spec.name == "duplicate_product_ref" and not payload_params:
        payload_params = {}
    if spec.name in ("delay_settle", "delay_render") and not payload_params:
        payload_params = {"seconds": 3.0} if spec.name == "delay_settle" else {"ms": 2500}

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        version = client.get("/_control/version", headers={control_header: control_token}).json()
        response = client.post(
            f"/_control/namespaces/{namespace}/mutate",
            json={"operator": spec.name, "params": payload_params},
            headers={control_header: control_token},
        )
        response.raise_for_status()
        result = response.json()

    if not result.get("applied"):
        manifest = _manifest(
            app=app,
            fixture_ref=fixture_ref,
            case_key=case_key,
            spec=spec,
            params=payload_params,
            patch={},
            seed=seed,
            version=version,
            valid=False,
            reason=str(result.get("reason") or "not_applied"),
        )
        return VariantOutcome(
            valid=False, reason=manifest["reason"], operator=spec.name, group=spec.group, manifest=manifest
        )

    patch = dict(result.get("patch") or {})
    verified, verify_reason = _verify_rendered(app, namespace, spec.name, payload_params, patch, base_url)
    if not verified:
        manifest = _manifest(
            app=app,
            fixture_ref=fixture_ref,
            case_key=case_key,
            spec=spec,
            params=payload_params,
            patch=patch,
            seed=seed,
            version=version,
            valid=False,
            reason=verify_reason or "effect_not_rendered",
        )
        return VariantOutcome(
            valid=False, reason=manifest["reason"], operator=spec.name, group=spec.group, manifest=manifest
        )

    manifest = _manifest(
        app=app,
        fixture_ref=fixture_ref,
        case_key=case_key,
        spec=spec,
        params=payload_params,
        patch=patch,
        seed=seed,
        version=version,
        valid=True,
        reason=None,
    )
    snapshot = {
        "schema_version": PUBLIC_TOKEN_SCHEMA,
        "variant_token": manifest["variant_token"],
        "app": app,
        "fixture_ref": fixture_ref,
        "build_digest": manifest["build_after"],
    }
    return VariantOutcome(
        valid=True, reason=None, operator=spec.name, group=spec.group, snapshot=snapshot, manifest=manifest
    )


def _manifest(
    *,
    app: str,
    fixture_ref: str,
    case_key: str,
    spec: OperatorSpec,
    params: dict[str, Any],
    patch: dict[str, Any],
    seed: int,
    version: dict[str, Any],
    valid: bool,
    reason: str | None,
) -> dict[str, Any]:
    token_material = digest_content(
        {
            "app": app,
            "fixture_ref": fixture_ref,
            "case_key": case_key,
            "operator": spec.name,
            "params": params,
            "patch": patch,
            "seed": seed,
        }
    )
    token = "v-" + token_material[:16]
    build_before = digest_content({"app": app, "app_version": version.get("version")})
    build_after = digest_content(
        {
            "app": app,
            "app_version": version.get("version"),
            "operator": spec.name,
            "params": params,
            "patch": patch,
            "seed": seed,
        }
    )
    return {
        "schema_version": MANIFEST_SCHEMA,
        "variant_token": token,
        "app": app,
        "fixture_ref": fixture_ref,
        "case_key": case_key,
        "operator": {"name": spec.name, "version": spec.version, "group": spec.group},
        "params": params,
        "seed": seed,
        "applied_patch": patch,
        "build_before": build_before,
        "build_after": build_after,
        "classification": {"group": spec.group, "expected_task_success": spec.group != "business_bug"},
        "valid": valid,
        "reason": reason,
        "oracle_assertions_ref": f"oracle:{case_key}:{token}",
    }


def write_public_snapshot(root: Path, snapshot: dict[str, Any]) -> Path:
    path = (
        root / "benchmarks" / "public" / "variant-tokens" / str(snapshot["app"]) / f"{snapshot['variant_token']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
