from __future__ import annotations

import json
from uuid import uuid4

import pytest
import yaml
from tests.support.security import csrf_headers

from agentqa.contracts.canonical import digest_content

pytestmark = pytest.mark.asyncio


async def _create_entity(api_client, csrf: str, workspace_id: str, kind: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/{kind}s",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _case_content(logical_key: str) -> dict:
    return {
        "schema_version": "case/1",
        "logical_key": logical_key,
        "title": "Ca portable",
        "goal": "Xác nhận đường dẫn",
        "requirements": ["portable_requirement"],
        "nodes": [
            {
                "id": "open",
                "kind": "action",
                "operation": "navigate",
                "value": {"kind": "literal", "value": "/start"},
                "side_effect": "read",
            },
            {
                "id": "check",
                "kind": "checkpoint",
                "assertions": [
                    {
                        "id": "path_reached",
                        "required": True,
                        "comparator": "url_path_equals",
                        "expected": {"kind": "literal", "value": "/done"},
                        "source_refs": ["portable_source"],
                    }
                ],
            },
        ],
        "source_defs": {
            "portable_source": {
                "source_content_digest": "a" * 64,
                "anchor": {"type": "section", "value": "flow"},
                "quote_digest": "b" * 64,
                "provenance": "user",
            }
        },
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["path_reached"]},
    }


async def _promote_case(api_client, csrf: str, workspace_id: str, logical_key: str) -> dict:
    case_id = await _create_entity(api_client, csrf, workspace_id, "case", logical_key)
    draft = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": _case_content(logical_key)},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert draft.status_code == 200, draft.text
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert promoted.status_code == 200, promoted.text
    return {"case_id": case_id, **promoted.json()}


async def _export(api_client, csrf: str, workspace_id: str, *, format: str = "yaml", kinds=None):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/exports",
        json={"kinds": kinds, "format": format},
        headers=csrf_headers(csrf),
    )


async def _import(api_client, csrf: str, workspace_id: str, *, format: str, content: str):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/imports",
        json={"format": format, "content": content},
        headers=csrf_headers(csrf),
    )


async def _second_workspace(api_client, csrf: str) -> str:
    response = await api_client.post(
        "/api/v1/workspaces",
        json={"slug": f"import-{uuid4().hex[:8]}", "name": "Import target"},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_workspace_bundle_roundtrip_remaps_ids(api_client, owner) -> None:
    workspace_id, csrf = owner
    requirement_id = await _create_entity(api_client, csrf, workspace_id, "requirement", "portable_requirement")
    requirement_revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/revisions",
        json={
            "content": {
                "schema_version": "requirement/1",
                "logical_key": "portable_requirement",
                "text": "Luồng di chuyển tới /done",
                "acceptance_statements": ["Đường dẫn kết thúc bằng /done"],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert requirement_revision.status_code == 200, requirement_revision.text
    promoted = await _promote_case(api_client, csrf, workspace_id, "portable_case")
    suite_id = await _create_entity(api_client, csrf, workspace_id, "suite", "portable_suite")
    suite_revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={
            "content": {
                "schema_version": "suite/1",
                "logical_key": "portable_suite",
                "case_refs": [{"logical_key": "portable_case", "revision_no": 1}],
                "fixture_refs": ["taskboard@1"],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert suite_revision.status_code == 200, suite_revision.text

    exported = await _export(api_client, csrf, workspace_id, kinds=["requirement", "case", "suite"])
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["schema_version"] == "workspace-bundle/1"
    assert len(body["digest"]) == 64
    assert "workspace_id" not in body["content"]
    assert "credential" not in body["content"]

    target = await _second_workspace(api_client, csrf)
    imported = await _import(api_client, csrf, target, format="yaml", content=body["content"])
    assert imported.status_code == 200, imported.text
    summaries = imported.json()["imported"]
    assert len(summaries) == 3
    assert {summary["revision_no"] for summary in summaries} == {1}

    cases = await api_client.get(f"/api/v1/workspaces/{target}/cases")
    assert [item["logical_key"] for item in cases.json()] == ["portable_case"]
    revisions = await api_client.get(f"/api/v1/workspaces/{target}/cases/{cases.json()[0]['id']}/revisions")
    assert revisions.json()[0]["content_digest"] == promoted["content_digest"]

    suites = await api_client.get(f"/api/v1/workspaces/{target}/suites")
    suite_target_id = suites.json()[0]["id"]
    suite_revisions = await api_client.get(f"/api/v1/workspaces/{target}/suites/{suite_target_id}/revisions")
    bind = await api_client.post(
        f"/api/v1/workspaces/{target}/suites/{suite_target_id}/revisions/{suite_revisions.json()[0]['revision_id']}/bind",
        headers=csrf_headers(csrf),
    )
    assert bind.status_code == 200, bind.text
    bind_body = bind.json()
    assert bind_body["facts"] == []
    assert len(bind_body["executions"]) == 1
    assert bind_body["executions"][0]["case_revision_id"] is not None
    assert bind_body["executions"][0]["case_revision_id"] != str(promoted["revision_id"])


async def test_import_rejects_foreign_rights_and_digest_mismatch(api_client, owner) -> None:
    workspace_id, csrf = owner
    await _promote_case(api_client, csrf, workspace_id, "rights_case")
    exported = await _export(api_client, csrf, workspace_id, kinds=["case"])
    bundle = yaml.safe_load(exported.json()["content"])
    item = bundle["sections"]["case"][0]

    poisoned = yaml.safe_load(exported.json()["content"])
    poisoned["sections"]["case"][0]["confirmation_ref"] = "foreign-approval"
    response = await _import(api_client, csrf, workspace_id, format="yaml", content=yaml.safe_dump(poisoned))
    assert response.status_code == 403

    approved = yaml.safe_load(exported.json()["content"])
    approved["sections"]["case"][0]["approved"] = True
    response = await _import(api_client, csrf, workspace_id, format="yaml", content=yaml.safe_dump(approved))
    assert response.status_code == 403

    tampered = yaml.safe_load(exported.json()["content"])
    tampered["sections"]["case"][0]["content_digest"] = "f" * 64
    response = await _import(api_client, csrf, workspace_id, format="yaml", content=yaml.safe_dump(tampered))
    assert response.status_code == 422

    malicious = "!!python/object/apply:os.system ['echo pwn']"
    response = await _import(api_client, csrf, workspace_id, format="yaml", content=malicious)
    assert response.status_code == 422

    assert item["content"]["logical_key"] == "rights_case"


async def test_import_validates_suite_bind_before_writes(api_client, owner) -> None:
    _workspace_id, csrf = owner
    target = await _second_workspace(api_client, csrf)
    bundle = {
        "schema_version": "workspace-bundle/1",
        "sections": {
            "suite": [
                {
                    "logical_key": "orphan_suite",
                    "revision_no": 1,
                    "content": {
                        "schema_version": "suite/1",
                        "logical_key": "orphan_suite",
                        "case_refs": [{"logical_key": "missing_case", "revision_no": 1}],
                    },
                    "content_digest": None,
                    "lifecycle": "ready",
                    "archived_at": None,
                }
            ]
        },
    }
    bundle["sections"]["suite"][0]["content_digest"] = digest_content(bundle["sections"]["suite"][0]["content"])
    response = await _import(api_client, csrf, target, format="json", content=json.dumps(bundle))
    assert response.status_code == 400
    assert "missing_case" in response.text

    suites = await api_client.get(f"/api/v1/workspaces/{target}/suites")
    assert suites.json() == []


async def test_export_import_json_roundtrip(api_client, owner) -> None:
    workspace_id, csrf = owner
    await _promote_case(api_client, csrf, workspace_id, "json_case")
    exported = await _export(api_client, csrf, workspace_id, format="json", kinds=["case"])
    assert exported.status_code == 200
    target = await _second_workspace(api_client, csrf)
    imported = await _import(api_client, csrf, target, format="json", content=exported.json()["content"])
    assert imported.status_code == 200, imported.text
    assert len(imported.json()["imported"]) == 1
