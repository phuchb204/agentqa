from __future__ import annotations

import pytest
import yaml
from tests.support.documents import make_docx, make_text_pdf
from tests.support.security import csrf_headers

from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import SourceAnchor
from agentqa.contracts.compiler import compile_case_document
from agentqa.contracts.errors import AgentQAValidationError
from agentqa.platform.revisions.service import validate_content

pytestmark = pytest.mark.asyncio

CANARY = "canary-anchor-4d1e7a"


async def _create_source(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _upload(api_client, csrf: str, workspace_id: str, source_id: str, filename: str, payload: bytes):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        data={"logical_key": "document"},
        files={"file": (filename, payload, "application/octet-stream")},
        headers=csrf_headers(csrf),
    )


def _case_content(
    *, requirement_key: str, source_name: str, source_digest: str, anchor: dict, quote_digest: str
) -> dict:
    return {
        "schema_version": "case/1",
        "logical_key": "source_linked_case",
        "title": "Ca có nguồn trích xuất",
        "goal": "Xác nhận SourceRef từ extraction dùng được trong compiler",
        "requirements": [requirement_key],
        "source_defs": {
            source_name: {
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
                        "source_refs": [source_name],
                    }
                ],
            },
        ],
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["path_reached"]},
    }


async def test_docx_never_reports_page_anchors(api_client, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "docx_anchor_source")
    payload = make_docx(heading="Mục một", paragraphs=["Nội dung đoạn văn."])
    response = await _upload(api_client, csrf, workspace_id, source_id, "doc.docx", payload)
    assert response.status_code == 200, response.text
    anchors = [segment["anchor"] for segment in response.json()["segments"]]
    assert anchors
    assert all(anchor["type"] != "page" for anchor in anchors)


async def test_missing_quote_digest_and_incomplete_table_cell_rejected() -> None:
    valid_source = {
        "source_content_digest": "a" * 64,
        "anchor": {"type": "page", "value": 1},
        "quote_digest": "b" * 64,
        "provenance": "user",
    }
    content = _case_content(
        requirement_key="flow_requirement",
        source_name="flow_requirement",
        source_digest="a" * 64,
        anchor={"type": "page", "value": 1},
        quote_digest="b" * 64,
    )
    validate_content("case", content)

    missing_quote = dict(content)
    missing_quote["source_defs"] = {"flow_requirement": {**valid_source, "quote_digest": "not-a-digest"}}
    with pytest.raises(AgentQAValidationError):
        validate_content("case", missing_quote)

    missing_digest = dict(content)
    missing_digest["source_defs"] = {"flow_requirement": {**valid_source, "source_content_digest": "xyz"}}
    with pytest.raises(AgentQAValidationError):
        validate_content("case", missing_digest)

    with pytest.raises(AgentQAValidationError):
        SourceAnchor.model_validate({"type": "table_cell", "value": "T0R0C0"})
    with pytest.raises(AgentQAValidationError):
        SourceAnchor.model_validate({"type": "page"})


async def test_source_ref_roundtrip_compiles_and_promotes(api_client, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "roundtrip_source")
    payload = make_text_pdf(["Checkout page shows order confirmation"])
    upload = await _upload(api_client, csrf, workspace_id, source_id, "spec.pdf", payload)
    assert upload.status_code == 200, upload.text
    revision = upload.json()["revision"]
    segment = upload.json()["segments"][0]

    content = _case_content(
        requirement_key="checkout_requirement",
        source_name="checkout_requirement",
        source_digest=revision["file_digest"],
        anchor=segment["anchor"],
        quote_digest=segment["text_digest"],
    )
    compiled = compile_case_document(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))
    assert compiled.content_digest

    created = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/cases",
        json={"logical_key": "source_linked_case"},
        headers=csrf_headers(csrf),
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
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
    assert promoted.json()["content_digest"] == digest_content(content)
    assert compiled.content_digest


async def test_redacted_segments_pass_taint_check(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    runtime.taint.register(CANARY)
    source_id = await _create_source(api_client, csrf, workspace_id, "taint_source")
    payload = f"# Ghi chú\n\nKhoá truy cập tạm là {CANARY}.".encode()
    response = await _upload(api_client, csrf, workspace_id, source_id, "notes.md", payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"]["privacy_class"] == "sensitive"
    runtime.taint.assert_clean(body, "model.input")
    assert all(segment["privacy"] == "redacted" for segment in body["segments"])
