from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from tests.support.platform import service_workspace
from tests.support.postgres import scoped_transaction

from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.artifacts.store import BlobStoreError, FaultBlobStore, FileSystemBlobStore
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.security.taint import SecretLeakError
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio

CANARY = "artifact-canary-8830"


async def test_stage_available_acl_and_digest(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    payload = b"evidence-bytes-1"
    view = await runtime.artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="evidence",
        media_type="image/png",
        payload=payload,
    )
    assert view.state == "available"
    assert view.digest == digest_artifact_bytes(payload)
    assert view.size_bytes == len(payload)
    assert view.object_key is not None
    assert runtime.artifacts.store.exists(view.object_key)
    assert (
        await runtime.artifacts.open_bytes(workspace_id=workspace_id, principal_id=user_id, artifact_id=view.id)
        == payload
    )

    other_user, _name, other_workspace = await service_workspace(runtime, label="other")
    with pytest.raises(IdentityError) as error:
        await runtime.artifacts.get_authorized(
            workspace_id=other_workspace, principal_id=other_user, artifact_id=view.id
        )
    assert error.value.code is ErrorCode.NOT_FOUND


async def test_blob_failure_keeps_proof(runtime, tmp_path) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    store = FaultBlobStore(tmp_path / "faulty", fail_on_write=True)
    service = ArtifactService(runtime.engines[ROLE_API], store)
    view = await service.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="trace",
        media_type="application/json",
        payload=b"cannot-write",
    )
    assert view.state == "unavailable"
    assert view.unavailable_reason == "blob_write_failed"
    assert view.object_key is not None
    assert view.digest is None

    fetched = await service.get_authorized(workspace_id=workspace_id, principal_id=user_id, artifact_id=view.id)
    assert fetched.state == "unavailable"


async def test_reconcile_publishes_staged_and_marks_orphans(runtime, tmp_path) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    store = FileSystemBlobStore(tmp_path / "recon")
    service = ArtifactService(runtime.engines[ROLE_API], store)
    with_blob_key = f"{workspace_id}/run/staged-with-blob"
    orphan_key = f"{workspace_id}/run/staged-orphan"
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        with_blob_id = (
            await session.execute(
                sa.insert(tables.artifacts)
                .values(
                    workspace_id=workspace_id,
                    kind="evidence",
                    state="staged",
                    media_type="image/png",
                    object_key=with_blob_key,
                )
                .returning(tables.artifacts.c.id)
            )
        ).scalar_one()
        orphan_id = (
            await session.execute(
                sa.insert(tables.artifacts)
                .values(
                    workspace_id=workspace_id,
                    kind="evidence",
                    state="staged",
                    media_type="image/png",
                    object_key=orphan_key,
                )
                .returning(tables.artifacts.c.id)
            )
        ).scalar_one()
    store.write(with_blob_key, b"reconciled-bytes")

    report = await service.reconcile(workspace_id=workspace_id, principal_id=user_id)
    assert report.scanned == 2
    assert report.published == 1
    assert report.unavailable == 1

    published = await service.get_authorized(workspace_id=workspace_id, principal_id=user_id, artifact_id=with_blob_id)
    assert published.state == "available"
    assert published.digest == digest_artifact_bytes(b"reconciled-bytes")
    orphan = await service.get_authorized(workspace_id=workspace_id, principal_id=user_id, artifact_id=orphan_id)
    assert orphan.state == "unavailable"
    assert orphan.unavailable_reason == "staged_without_blob"


async def test_tombstone_keeps_provenance(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    view = await runtime.artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="report",
        media_type="text/html",
        payload=b"report-bytes",
        retention="workspace",
    )
    tombstoned = await runtime.artifacts.tombstone(
        workspace_id=workspace_id, principal_id=user_id, artifact_id=view.id, reason="retention_expired"
    )
    assert tombstoned.state == "deleted"
    assert tombstoned.tombstoned_at is not None
    assert tombstoned.digest == view.digest


async def test_canary_is_blocked_before_storage(runtime) -> None:
    user_id, _username, workspace_id = await service_workspace(runtime)
    runtime.taint.register(CANARY)
    with pytest.raises(SecretLeakError):
        await runtime.artifacts.stage(
            workspace_id=workspace_id,
            principal_id=user_id,
            kind="evidence",
            media_type="text/plain",
            payload=f"Bearer {CANARY}".encode(),
        )
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        count = (await session.execute(sa.select(sa.func.count()).select_from(tables.artifacts))).scalar_one()
    assert count == 0


async def test_object_key_safety(tmp_path) -> None:
    store = FileSystemBlobStore(tmp_path / "safe")
    for unsafe in ("../escape", "/absolute", "a/../../b", "", "dir\\windows"):
        with pytest.raises(BlobStoreError):
            store.write(unsafe, b"x")

    if os.name == "nt":
        pytest.skip("symlink test chỉ chạy trên nền tảng hỗ trợ")
    link = store.root / "link"
    try:
        os.symlink(tmp_path, link)
    except OSError:
        pytest.skip("không tạo được symlink trong môi trường này")
    with pytest.raises(BlobStoreError):
        store.write("link/inside", b"x")
