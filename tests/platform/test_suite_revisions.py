from __future__ import annotations

import pytest
from tests.support.security import csrf_headers

pytestmark = pytest.mark.asyncio


def _case_content(logical_key: str) -> dict:
    return {
        "schema_version": "case/1",
        "logical_key": logical_key,
        "title": "Ca cho suite",
        "goal": "Xác nhận đường dẫn",
        "requirements": ["suite_requirement"],
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
                        "source_refs": ["suite_source"],
                    }
                ],
            },
        ],
        "source_defs": {
            "suite_source": {
                "source_content_digest": "a" * 64,
                "anchor": {"type": "section", "value": "flow"},
                "quote_digest": "b" * 64,
                "provenance": "user",
            }
        },
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["path_reached"]},
    }


async def _create_entity(api_client, csrf: str, workspace_id: str, kind: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/{kind}s",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _promote_case(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    case_id = await _create_entity(api_client, csrf, workspace_id, "case", logical_key)
    await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": _case_content(logical_key)},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert promoted.status_code == 200, promoted.text
    return promoted.json()["revision_id"]


async def test_suite_revision_pins_case_revision_and_binds(api_client, owner) -> None:
    workspace_id, csrf = owner
    revision_id = await _promote_case(api_client, csrf, workspace_id, "suite_case")
    suite_id = await _create_entity(api_client, csrf, workspace_id, "suite", "suite_smoke")
    content = {
        "schema_version": "suite/1",
        "logical_key": "suite_smoke",
        "case_refs": [{"logical_key": "suite_case", "revision_no": 1}],
        "fixture_refs": ["taskboard@1"],
    }
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={"content": content},
        headers=csrf_headers(csrf),
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["revision_no"] == 1

    bind = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions/{promoted.json()['revision_id']}/bind",
        headers=csrf_headers(csrf),
    )
    assert bind.status_code == 200, bind.text
    body = bind.json()
    assert body["suite_logical_key"] == "suite_smoke"
    assert body["fixture_refs"] == ["taskboard@1"]
    assert body["facts"] == []
    assert len(body["executions"]) == 1
    execution = body["executions"][0]
    assert execution["case_revision_id"] == revision_id
    assert execution["dataset_row_index"] is None
    assert execution["execution_key"].startswith(f"{promoted.json()['revision_id']}:suite_case:1:")

    second = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={"content": content},
        headers=csrf_headers(csrf),
    )
    assert second.status_code == 200
    assert second.json()["revision_no"] == 2
    assert second.json()["supersedes"] == promoted.json()["revision_id"]


async def test_suite_bind_reports_missing_refs_without_actions(api_client, owner) -> None:
    workspace_id, csrf = owner
    await _promote_case(api_client, csrf, workspace_id, "pinned_case")
    suite_id = await _create_entity(api_client, csrf, workspace_id, "suite", "stale_suite")
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={
            "content": {
                "schema_version": "suite/1",
                "logical_key": "stale_suite",
                "case_refs": [
                    {"logical_key": "pinned_case", "revision_no": 2},
                    {"logical_key": "missing_case", "revision_no": 1},
                ],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert promoted.status_code == 200, promoted.text
    bind = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions/{promoted.json()['revision_id']}/bind",
        headers=csrf_headers(csrf),
    )
    assert bind.status_code == 200, bind.text
    body = bind.json()
    assert set(body["facts"]) == {"missing_case:missing_case", "missing_case_revision:pinned_case@2"}
    assert len(body["executions"]) == 2
    assert all(execution["case_revision_id"] is None for execution in body["executions"])
