from __future__ import annotations

from uuid import UUID

import pytest
from tests.support.security import csrf_headers

from agentqa.contracts.canonical import digest_content

pytestmark = pytest.mark.asyncio


def _case_content(logical_key: str) -> dict:
    return {
        "schema_version": "case/1",
        "logical_key": logical_key,
        "title": "Ca cho data rows",
        "goal": "Xác nhận đường dẫn",
        "requirements": ["data_requirement"],
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
                        "source_refs": ["data_source"],
                    }
                ],
            },
        ],
        "source_defs": {
            "data_source": {
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


async def _promote_dataset(api_client, csrf: str, workspace_id: str, rows: list) -> tuple[str, dict]:
    dataset_id = await _create_entity(api_client, csrf, workspace_id, "dataset", "rows_dataset")
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/revisions",
        json={
            "content": {
                "schema_version": "dataset/1",
                "logical_key": "rows_dataset",
                "privacy_class": "synthetic",
                "rows": rows,
            }
        },
        headers=csrf_headers(csrf),
    )
    assert promoted.status_code == 200, promoted.text
    return dataset_id, promoted.json()


async def test_dataset_rows_have_identity_and_bind_per_row(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    rows = [{"item_name": "Việc A"}, {"item_name": "Việc B"}]
    dataset_id, promoted = await _promote_dataset(api_client, csrf, workspace_id, rows)

    row_views = await runtime.datasets.rows(
        workspace_id=UUID(workspace_id),
        principal_id=(await runtime.users.create(username="rows-reader", password="pw-123456")).id,
        dataset_revision_id=UUID(promoted["revision_id"]),
    )
    assert [view.index for view in row_views] == [0, 1]
    assert [view.parameters for view in row_views] == rows
    assert row_views[0].row_digest == digest_content(rows[0])
    assert row_views[0].row_digest != row_views[1].row_digest

    await _promote_case(api_client, csrf, workspace_id, "rows_case")
    suite_id = await _create_entity(api_client, csrf, workspace_id, "suite", "rows_suite")
    suite_revision = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions",
        json={
            "content": {
                "schema_version": "suite/1",
                "logical_key": "rows_suite",
                "case_refs": [{"logical_key": "rows_case", "revision_no": 1}],
                "dataset_ref": "rows_dataset",
            }
        },
        headers=csrf_headers(csrf),
    )
    assert suite_revision.status_code == 200, suite_revision.text
    bind = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions/{suite_revision.json()['revision_id']}/bind",
        headers=csrf_headers(csrf),
    )
    assert bind.status_code == 200, bind.text
    body = bind.json()
    assert body["facts"] == []
    assert len(body["executions"]) == 2
    assert [execution["dataset_row_index"] for execution in body["executions"]] == [0, 1]
    assert [execution["parameters"] for execution in body["executions"]] == rows
    keys = [execution["execution_key"] for execution in body["executions"]]
    assert len(set(keys)) == 2
    assert dataset_id


async def test_dataset_rows_validation_rejects_non_objects(api_client, owner) -> None:
    workspace_id, csrf = owner
    dataset_id = await _create_entity(api_client, csrf, workspace_id, "dataset", "invalid_rows")
    invalid = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/revisions",
        json={
            "content": {
                "schema_version": "dataset/1",
                "logical_key": "invalid_rows",
                "rows": ["not-an-object"],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert invalid.status_code == 422

    pii = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/revisions",
        json={
            "content": {
                "schema_version": "dataset/1",
                "logical_key": "invalid_rows",
                "privacy_class": "pii",
                "rows": [{"customer": "an"}],
            }
        },
        headers=csrf_headers(csrf),
    )
    assert pii.status_code == 200, pii.text
    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/datasets/{dataset_id}/revisions")
    assert revisions.json()[0]["content"]["privacy_class"] == "pii"
