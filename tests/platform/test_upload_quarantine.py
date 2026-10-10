from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from tests.support.documents import (
    make_encrypted_pdf,
    make_external_entity_docx,
    make_macro_docx,
    make_traversal_docx,
    make_zip_bomb_docx,
)
from tests.support.postgres import scoped_transaction
from tests.support.security import csrf_headers

from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio

CANARY = "canary-credential-9f3b2c"


async def _create_source(api_client, csrf: str, workspace_id: str, logical_key: str) -> str:
    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        json={"logical_key": logical_key},
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _upload(
    api_client,
    csrf: str,
    workspace_id: str,
    source_id: str,
    *,
    filename: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
    logical_key: str = "document",
):
    return await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        data={"logical_key": logical_key},
        files={"file": (filename, payload, content_type)},
        headers=csrf_headers(csrf),
    )


async def _latest_revision(runtime, workspace_id: str, source_id: str):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        return (
            await session.execute(
                sa.select(tables.source_revisions)
                .where(tables.source_revisions.c.source_id == UUID(source_id))
                .order_by(tables.source_revisions.c.revision_no.desc())
                .limit(1)
            )
        ).one()


async def _job(runtime, workspace_id: str, revision_id: UUID):
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        return (
            await session.execute(
                sa.select(tables.extraction_jobs).where(tables.extraction_jobs.c.source_revision_id == revision_id)
            )
        ).one()


async def test_valid_upload_extracts_and_records_job(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "purchase_spec")
    payload = "# Quy trình mua hàng\n\nNgười dùng tạo yêu cầu mua và xác nhận tổng tiền.".encode()

    response = await _upload(
        api_client, csrf, workspace_id, source_id, filename="spec.md", payload=payload, content_type="text/markdown"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"]["state"] == "extracted"
    assert body["revision"]["revision_no"] == 1
    assert body["revision"]["privacy_class"] == "standard"
    assert len(body["revision"]["file_digest"]) == 64
    assert body["revision"]["segment_count"] == len(body["segments"]) == 1
    segment = body["segments"][0]
    assert segment["anchor"]["type"] == "section"
    assert segment["anchor"]["value"] == "Quy trình mua hàng"
    assert segment["anchor"]["table_index"] is None
    assert segment["text"] == "Người dùng tạo yêu cầu mua và xác nhận tổng tiền."
    assert segment["text_digest"] == sha256(segment["text"].encode("utf-8")).hexdigest()
    assert segment["privacy"] == "safe"

    row = await _latest_revision(runtime, workspace_id, source_id)
    assert row.state == "extracted"
    job = await _job(runtime, workspace_id, row.id)
    assert job.state == "succeeded"
    assert job.finished_at is not None

    assert runtime.artifacts.store.exists(row.object_key)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        artifact_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(tables.artifacts)
            .where(tables.artifacts.c.workspace_id == UUID(workspace_id))
        )
    assert artifact_count == 0


@pytest.mark.parametrize(
    ("filename", "payload", "reason"),
    [
        ("broken.pdf", b"%PDF-1.4\nthis is not a real pdf body", "invalid_pdf"),
        ("encrypted.pdf", make_encrypted_pdf(), "encrypted_file"),
        ("bomb.docx", make_zip_bomb_docx(), "decompression_bomb"),
        ("macro.docx", make_macro_docx(), "macro_content"),
        ("entity.docx", make_external_entity_docx(), "external_entity"),
        ("traversal.docx", make_traversal_docx(), "path_traversal"),
        ("empty.txt", b"", "empty_file"),
        ("wrong.docx", b"PK\x03\x04not a zip", "invalid_docx"),
    ],
)
async def test_rejected_uploads_are_quarantined_with_reason(
    api_client, runtime, owner, filename: str, payload: bytes, reason: str
) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, f"source_{reason}")
    response = await _upload(api_client, csrf, workspace_id, source_id, filename=filename, payload=payload)
    assert response.status_code == 422, response.text

    row = await _latest_revision(runtime, workspace_id, source_id)
    assert row.state == "rejected"
    assert row.unextractable_reason == reason
    job = await _job(runtime, workspace_id, row.id)
    assert job.state == "failed"
    assert job.reason == reason


async def test_oversize_upload_is_rejected(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "big_source")
    payload = b"a" * (20 * 1024 * 1024 + 1)
    response = await _upload(api_client, csrf, workspace_id, source_id, filename="big.txt", payload=payload)
    assert response.status_code == 422
    row = await _latest_revision(runtime, workspace_id, source_id)
    assert row.state == "rejected"
    assert row.unextractable_reason == "size_exceeded"


async def test_duplicate_source_identity_and_revision_numbering(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "duplicate_source")
    duplicate = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        json={"logical_key": "duplicate_source"},
        headers=csrf_headers(csrf),
    )
    assert duplicate.status_code == 409

    payload = b"# Section\n\nSame content twice"
    first = await _upload(api_client, csrf, workspace_id, source_id, filename="a.md", payload=payload)
    second = await _upload(api_client, csrf, workspace_id, source_id, filename="a.md", payload=payload)
    assert first.status_code == 200 and second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert first_body["revision"]["revision_no"] == 1
    assert second_body["revision"]["revision_no"] == 2
    assert first_body["revision"]["file_digest"] == second_body["revision"]["file_digest"]
    assert first_body["revision"]["revision_id"] != second_body["revision"]["revision_id"]

    revisions = await api_client.get(f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions")
    assert revisions.status_code == 200
    assert [item["revision_no"] for item in revisions.json()] == [1, 2]


async def test_credentials_in_upload_are_redacted_before_storage(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    runtime.taint.register(CANARY)
    source_id = await _create_source(api_client, csrf, workspace_id, "credentialed_source")
    payload = f"# Cấu hình\n\nTài khoản demo dùng mật khẩu {CANARY} để đăng nhập.".encode()

    response = await _upload(
        api_client, csrf, workspace_id, source_id, filename="config.md", payload=payload, content_type="text/markdown"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert CANARY not in response.text
    assert body["revision"]["privacy_class"] == "sensitive"
    assert body["segments"][0]["privacy"] == "redacted"
    assert "[REDACTED]" in body["segments"][0]["text"]
    runtime.taint.assert_clean(body, "model.input")

    detail = await api_client.get(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions/{body['revision']['revision_no']}"
    )
    assert detail.status_code == 200
    assert CANARY not in detail.text

    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        texts = (
            (
                await session.execute(
                    sa.select(tables.source_segments.c.text).where(
                        tables.source_segments.c.workspace_id == UUID(workspace_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        artifact_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(tables.artifacts)
            .where(tables.artifacts.c.workspace_id == UUID(workspace_id))
        )
    assert texts and all(CANARY not in text for text in texts)
    assert artifact_count == 0


async def test_extract_endpoint_processes_pending_revision(api_client, runtime, owner) -> None:
    workspace_id, csrf = owner
    source_id = await _create_source(api_client, csrf, workspace_id, "pending_source")
    revision_id = uuid4()
    object_key = f"sources/{workspace_id}/{revision_id}"
    payload = b"# Pending\n\nNoi dung cho extraction tre."
    runtime.artifacts.store.write(object_key, payload)
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=uuid4(), workspace_id=UUID(workspace_id)
    ) as session:
        await session.execute(
            sa.insert(tables.source_revisions).values(
                id=revision_id,
                workspace_id=UUID(workspace_id),
                source_id=UUID(source_id),
                revision_no=1,
                filename="pending.md",
                media_type="text/markdown",
                size_bytes=len(payload),
                file_digest=sha256(payload).hexdigest(),
                state="quarantined",
                object_key=object_key,
            )
        )
        await session.execute(
            sa.insert(tables.extraction_jobs).values(
                workspace_id=UUID(workspace_id), source_revision_id=revision_id, state="queued"
            )
        )

    response = await api_client.post(
        f"/api/v1/workspaces/{workspace_id}/sources/{source_id}/extract",
        headers=csrf_headers(csrf),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"]["state"] == "extracted"
    assert body["segments"][0]["text"] == "Noi dung cho extraction tre."
    job = await _job(runtime, workspace_id, revision_id)
    assert job.state == "succeeded"
