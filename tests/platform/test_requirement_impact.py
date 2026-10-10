from __future__ import annotations

from uuid import uuid4

import pytest
from tests.support.documents import make_text_pdf
from tests.support.security import csrf_headers

pytestmark = pytest.mark.asyncio


async def _create_entity(api_client, csrf: str, workspace_id: str, kind: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/{kind}s",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _promote_requirement(api_client, csrf: str, workspace_id: str, requirement_id: str, content: dict):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/revisions",
        json={"content": content},
        headers=csrf_headers(csrf),
    )


async def _create_source(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _requirement_content(*, text: str, source_refs: list[str]) -> dict:
    return {
        "schema_version": "requirement/1",
        "logical_key": "checkout_rule",
        "text": text,
        "source_refs": source_refs,
        "acceptance_statements": ["Trang xác nhận đơn hiển thị tổng tiền"],
        "tags": ["checkout"],
    }


def _case_content(*, source_digest: str, anchor: dict, quote_digest: str) -> dict:
    return {
        "schema_version": "case/1",
        "logical_key": "checkout_case",
        "title": "Ca checkout",
        "goal": "Xác nhận đường dẫn hoàn tất",
        "requirements": ["checkout_rule"],
        "source_defs": {
            "checkout_source": {
                "source_content_digest": source_digest,
                "anchor": anchor,
                "quote_digest": quote_digest,
                "provenance": "user",
            }
        },
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
                        "source_refs": ["checkout_source"],
                    }
                ],
            },
        ],
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["path_reached"]},
    }


async def test_requirement_update_marks_linked_cases_without_touching_revisions(api_client, owner) -> None:
    workspace_id, csrf = owner
    requirement_id = await _create_entity(api_client, csrf, workspace_id, "requirement", "checkout_rule")
    first = await _promote_requirement(
        api_client,
        csrf,
        workspace_id,
        requirement_id,
        _requirement_content(text="Đơn hàng được xác nhận", source_refs=["checkout_source"]),
    )
    assert first.status_code == 200, first.text
    assert first.json()["revision_no"] == 1

    source_id = await _create_source(api_client, csrf, workspace_id, "checkout_source")
    upload = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        data={"logical_key": "checkout_source"},
        files={"file": ("checkout.pdf", make_text_pdf(["Order confirmation page"]), "application/pdf")},
        headers=csrf_headers(csrf),
    )
    assert upload.status_code == 200, upload.text
    revision = upload.json()["revision"]
    segment = upload.json()["segments"][0]

    case_id = await _create_entity(api_client, csrf, workspace_id, "case", "checkout_case")
    content = _case_content(
        source_digest=revision["file_digest"], anchor=segment["anchor"], quote_digest=segment["text_digest"]
    )
    draft = await api_client.patch(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft",
        json={"content": content},
        headers={**csrf_headers(csrf), "If-Match": '"0"'},
    )
    assert draft.status_code == 200, draft.text
    promoted = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        headers={**csrf_headers(csrf), "If-Match": '"1"'},
    )
    assert promoted.status_code == 200, promoted.text
    case_digest = promoted.json()["content_digest"]

    impact = await api_client.get(f"/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/impact")
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert body["latest_revision_no"] == 1
    assert len(body["links"]) == 1
    link = body["links"][0]
    assert link["logical_key"] == "checkout_case"
    assert link["needs_review"] is False
    assert link["affected_assertions"] == ["path_reached"]
    assert link["affected_nodes"] == ["check"]
    assert link["source_names"] == ["checkout_source"]

    second = await _promote_requirement(
        api_client,
        csrf,
        workspace_id,
        requirement_id,
        _requirement_content(text="Đơn hàng được xác nhận và gửi email", source_refs=["checkout_source"]),
    )
    assert second.status_code == 200, second.text
    assert second.json()["revision_no"] == 2

    impact_after = await api_client.get(f"/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/impact")
    assert impact_after.status_code == 200
    body_after = impact_after.json()
    assert body_after["latest_revision_no"] == 2
    link_after = body_after["links"][0]
    assert link_after["needs_review"] is True
    assert link_after["review_marked_at"] is not None
    assert link_after["case_revision_id"] == link["case_revision_id"]

    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions")
    assert revisions.status_code == 200
    case_revision = revisions.json()[0]
    assert case_revision["content_digest"] == case_digest
    assert case_revision["lifecycle"] == "ready"
    assertion = case_revision["content"]["nodes"][1]["assertions"][0]
    assert assertion["source_refs"] == ["checkout_source"]


async def test_impact_requires_scoped_requirement(api_client, owner) -> None:
    workspace_id, csrf = owner
    missing = await api_client.get(f"/api/v1/workspaces/{workspace_id}/requirements/{uuid4()}/impact")
    assert missing.status_code == 404

    other = await api_client.post(
        "/api/v1/workspaces",
        json={"slug": f"other-{uuid4().hex[:8]}", "name": "other"},
        headers=csrf_headers(csrf),
    )
    assert other.status_code == 200, other.text
    other_workspace = other.json()["id"]
    requirement_id = await _create_entity(api_client, csrf, workspace_id, "requirement", "scoped_rule")
    cross = await api_client.get(f"/api/v1/workspaces/{other_workspace}/requirements/{requirement_id}/impact")
    assert cross.status_code == 404


async def test_requirement_revision_validation(api_client, owner) -> None:
    workspace_id, csrf = owner
    requirement_id = await _create_entity(api_client, csrf, workspace_id, "requirement", "invalid_rule")
    invalid = await _promote_requirement(
        api_client, csrf, workspace_id, requirement_id, {"schema_version": "requirement/1", "text": "Thiếu logical key"}
    )
    assert invalid.status_code == 422
    valid = await _promote_requirement(
        api_client,
        csrf,
        workspace_id,
        requirement_id,
        {
            "schema_version": "requirement/1",
            "logical_key": "invalid_rule",
            "text": "Yêu cầu hợp lệ",
            "acceptance_statements": ["Có tiêu chí"],
        },
    )
    assert valid.status_code == 200, valid.text
