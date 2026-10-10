from __future__ import annotations

import subprocess
import sys
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from tests.support.documents import make_blank_pdf, make_docx, make_text_pdf
from tests.support.postgres import scoped_transaction
from tests.support.security import csrf_headers

from agentqa.platform.extraction.service import NETWORK_BLOCK_PREAMBLE, _sandbox_environment
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _create_source(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _upload(
    api_client, csrf: str, workspace_id: str, source_id: str, filename: str, payload: bytes, media_type: str
):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        data={"logical_key": "document"},
        files={"file": (filename, payload, media_type)},
        headers=csrf_headers(csrf),
    )


async def test_pdf_page_anchors_and_digests(api_client, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "pdf_source")
    payload = make_text_pdf(["First page body", "Second page body"])
    response = await _upload(api_client, csrf, workspace_id, source_id, "report.pdf", payload, "application/pdf")
    assert response.status_code == 200, response.text
    segments = response.json()["segments"]
    assert [segment["anchor"]["type"] for segment in segments] == ["page", "page"]
    assert [segment["anchor"]["value"] for segment in segments] == [1, 2]
    assert [segment["text"] for segment in segments] == ["First page body", "Second page body"]
    for segment in segments:
        assert segment["text_digest"] == sha256(segment["text"].encode("utf-8")).hexdigest()


async def test_docx_unicode_heading_paragraph_and_table_anchors(api_client, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "docx_source")
    payload = make_docx(
        heading="Quy trình đặt hàng",
        paragraphs=["Khách hàng chọn sản phẩm và xác nhận đơn.", "Hệ thống gửi email xác nhận."],
        tables=[[["Mã", "Số lượng"], ["SP-001", "2"]]],
    )
    response = await _upload(
        api_client,
        csrf,
        workspace_id,
        source_id,
        "spec.docx",
        payload,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert response.status_code == 200, response.text
    segments = response.json()["segments"]
    anchors = [segment["anchor"] for segment in segments]
    assert anchors[0]["type"] == "heading"
    assert anchors[0]["value"] == "Quy trình đặt hàng"
    assert {anchor["type"] for anchor in anchors} == {"heading", "paragraph", "table_cell"}
    table_cell = next(anchor for anchor in anchors if anchor["type"] == "table_cell")
    assert table_cell["table_index"] == 0
    assert table_cell["row"] == 0
    assert table_cell["column"] == 0
    texts = [segment["text"] for segment in segments]
    assert "Khách hàng chọn sản phẩm và xác nhận đơn." in texts
    assert "SP-001" in texts


async def test_image_only_pdf_is_unextractable_without_fabrication(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "scan_source")
    response = await _upload(
        api_client, csrf, workspace_id, source_id, "scan.pdf", make_blank_pdf(2), "application/pdf"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"]["state"] == "unextractable"
    assert body["revision"]["unextractable_reason"] == "no_extractable_text"
    assert body["revision"]["segment_count"] == 0
    assert body["segments"] == []

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        job = (
            await session.execute(
                sa.select(tables.extraction_jobs).where(
                    tables.extraction_jobs.c.source_revision_id == UUID(body["revision"]["revision_id"])
                )
            )
        ).one()
    assert job.state == "unextractable"
    assert job.reason == "no_extractable_text"


async def test_extraction_subprocess_blocks_network() -> None:
    probe = (
        NETWORK_BLOCK_PREAMBLE
        + "\nimport socket\n\n"
        + "try:\n    socket.getaddrinfo('example.com', 80)\n"
        + "except OSError:\n    print('blocked')\n"
        + "else:\n    raise SystemExit(3)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert "blocked" in completed.stdout


async def test_sandbox_environment_excludes_provider_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AGENTQA_LLM_API_KEY", "canary-key")
    monkeypatch.setenv("AGENTQA_JEV_API_KEY", "canary-key")
    environment = _sandbox_environment()
    assert all(not name.startswith("AGENTQA_") for name in environment)
    assert environment["PYTHONIOENCODING"] == "utf-8"
