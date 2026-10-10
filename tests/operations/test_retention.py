from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.support.postgres import scoped_transaction, seed_workspace

from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.artifacts.store import FaultBlobStore, FileSystemBlobStore
from agentqa.platform.retention import RetentionService
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def _backdate(engines, *, workspace_id, principal_id, artifact_id, days: int) -> None:
    async with scoped_transaction(engines[ROLE_API], principal_id=principal_id, workspace_id=workspace_id) as session:
        await session.execute(
            sa.update(tables.artifacts)
            .where(tables.artifacts.c.id == artifact_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )


async def test_expired_artifact_is_tombstoned_then_swept(role_engines, tmp_path: Path) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="retention")
    store = FileSystemBlobStore(tmp_path / "store")
    artifacts = ArtifactService(engines[ROLE_API], store)
    view = await artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="screenshot",
        media_type="image/png",
        payload=b"evidence-bytes",
        retention="run",
    )
    await _backdate(engines, workspace_id=workspace_id, principal_id=user_id, artifact_id=view.id, days=8)
    retention = RetentionService(engines[ROLE_API], store, ttls_days={"run": 7, "workspace": 30, "research": 365})

    expired = await retention.expire_due(workspace_id=workspace_id, principal_id=user_id)
    assert expired == 1
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        row = (await session.execute(sa.select(tables.artifacts).where(tables.artifacts.c.id == view.id))).one()
    assert row.state == "deleted"
    assert row.tombstoned_at is not None
    assert row.unavailable_reason == "retention_expired:run"
    assert row.digest == view.digest
    assert store.exists(row.object_key)

    swept = await retention.sweep_tombstones(workspace_id=workspace_id, principal_id=user_id)
    assert swept == 1
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        row = (await session.execute(sa.select(tables.artifacts).where(tables.artifacts.c.id == view.id))).one()
    assert row.state == "deleted"
    assert row.object_key is None
    assert row.digest == view.digest
    assert await retention.sweep_tombstones(workspace_id=workspace_id, principal_id=user_id) == 0


async def test_fresh_and_staged_artifacts_are_not_expired(role_engines, tmp_path: Path) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="retention-fresh")
    store = FileSystemBlobStore(tmp_path / "store")
    artifacts = ArtifactService(engines[ROLE_API], store)
    fresh = await artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="dom",
        media_type="text/html",
        payload=b"<html/>",
        retention="run",
    )
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        staged_id = uuid4()
        await session.execute(
            sa.insert(tables.artifacts).values(
                id=staged_id,
                workspace_id=workspace_id,
                kind="screenshot",
                state="staged",
                retention="run",
                object_key=f"{workspace_id}/unassigned/{staged_id}",
                created_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
    retention = RetentionService(engines[ROLE_API], store, ttls_days={"run": 7})
    expired = await retention.expire_due(workspace_id=workspace_id, principal_id=user_id)
    assert expired == 0
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        states = {
            row.id: row.state
            for row in (
                await session.execute(
                    sa.select(tables.artifacts.c.id, tables.artifacts.c.state).where(
                        tables.artifacts.c.workspace_id == workspace_id
                    )
                )
            ).all()
        }
    assert states[fresh.id] == "available"
    assert states[staged_id] == "staged"


async def test_orphan_scan_reports_without_deleting(role_engines, tmp_path: Path) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="retention-orphan")
    store = FileSystemBlobStore(tmp_path / "store")
    orphan_key = f"{workspace_id}/unassigned/{uuid4()}"
    store.write(orphan_key, b"orphan-bytes")
    retention = RetentionService(engines[ROLE_API], store)
    orphans = await retention.scan_orphans(workspace_id=workspace_id, principal_id=user_id)
    assert orphan_key in orphans
    assert store.exists(orphan_key)


async def test_failed_write_is_unavailable_and_counted(role_engines, tmp_path: Path) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="retention-fault")
    store = FaultBlobStore(tmp_path / "store", fail_on_write=True)
    artifacts = ArtifactService(engines[ROLE_API], store)
    view = await artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="screenshot",
        media_type="image/png",
        payload=b"will-fail",
        retention="run",
    )
    assert view.state == "unavailable"
    assert view.unavailable_reason == "blob_write_failed"
    retention = RetentionService(engines[ROLE_API], store)
    assert await retention.count_failed_writes(workspace_id=workspace_id, principal_id=user_id) == 1


async def test_staged_reconciliation_marks_missing_blob(role_engines, tmp_path: Path) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label="retention-reconcile")
    store = FileSystemBlobStore(tmp_path / "store")
    artifacts = ArtifactService(engines[ROLE_API], store)
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        staged_id = uuid4()
        await session.execute(
            sa.insert(tables.artifacts).values(
                id=staged_id,
                workspace_id=workspace_id,
                kind="screenshot",
                state="staged",
                retention="run",
                object_key=f"{workspace_id}/unassigned/{staged_id}",
            )
        )
    report = await artifacts.reconcile(workspace_id=workspace_id, principal_id=user_id)
    assert report.unavailable == 1
    async with scoped_transaction(engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id) as session:
        row = (await session.execute(sa.select(tables.artifacts).where(tables.artifacts.c.id == staged_id))).one()
    assert row.state == "unavailable"
    assert row.unavailable_reason == "staged_without_blob"
