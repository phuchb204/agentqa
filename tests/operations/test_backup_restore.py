from __future__ import annotations

import json
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.support.postgres import seed_execution, seed_run, seed_workspace

from agentqa.platform.artifacts.service import ArtifactService
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.backup import (
    BackupService,
    IntegrityError,
    KeyringRestoreError,
    backup_keyring,
    restore_keyring,
)
from agentqa.platform.identity.sessions import SessionService
from agentqa.platform.security.credentials import MasterKeyring
from agentqa.platform.storage.roles import ROLE_API, ROLE_MIGRATE, admin_dsn, drop_database, role_dsn

pytestmark = pytest.mark.asyncio


async def _seed_backup_state(role_engines, tmp_path: Path) -> dict:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"backup-{uuid4().hex[:8]}")
    store = FileSystemBlobStore(tmp_path / "store")
    artifacts = ArtifactService(engines[ROLE_API], store)
    view = await artifacts.stage(
        workspace_id=workspace_id,
        principal_id=user_id,
        kind="screenshot",
        media_type="image/png",
        payload=b"backup-evidence",
        retention="run",
    )
    sessions = SessionService(engines[ROLE_API])
    login = await sessions.create_for_user(user_id=user_id, username="backup-user")
    run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id, status="running")
    await seed_execution(
        engines, principal_id=user_id, workspace_id=workspace_id, run_id=run_id, logical_key="backup-case"
    )
    return {
        "engines": engines,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "store": store,
        "artifact": view,
        "session_token": login.raw_token,
        "run_id": run_id,
    }


async def test_backup_verify_and_restore_isolated(role_engines, test_db, tmp_path: Path) -> None:
    state = await _seed_backup_state(role_engines, tmp_path)
    service = BackupService(admin_dsn(test_db.name), artifact_root=state["store"].root)
    backup_dir = tmp_path / "backup"
    from agentqa.platform.storage.migrate import alembic_head_revision

    manifest = await service.create(backup_dir)
    assert manifest.schema_version == alembic_head_revision()
    assert manifest.table_counts["workspaces"] >= 1
    assert manifest.table_counts["artifacts"] >= 1
    prefix = f"{state['workspace_id']}/"
    assert any(key.startswith(prefix) for key in manifest.blobs)
    service.verify(backup_dir)

    data_file = backup_dir / "data" / "workspaces.jsonl"
    original = data_file.read_text(encoding="utf-8")
    tampered = original.replace("name", "nXme", 1)
    data_file.write_text(tampered, encoding="utf-8")
    with pytest.raises(IntegrityError):
        service.verify(backup_dir)
    data_file.write_text(original, encoding="utf-8")
    service.verify(backup_dir)

    database = f"agentqa_test_restore_{secrets.token_hex(4)}"
    admin = admin_dsn()
    try:
        report = await service.restore(backup_dir, database=database, migrate_dsn=role_dsn(ROLE_MIGRATE, database))
        assert report.failures == []
        assert report.table_counts["workspaces"] == manifest.table_counts["workspaces"]
        assert report.table_counts["artifacts"] == manifest.table_counts["artifacts"]
        assert report.links_ok is True
        assert report.session_revoked >= 1
        assert report.runs_quarantined >= 1

        from sqlalchemy.ext.asyncio import create_async_engine
        from tests.support.postgres import scoped_transaction

        async_engine = create_async_engine(role_dsn(ROLE_API, database))
        try:
            async with scoped_transaction(
                async_engine, principal_id=state["user_id"], workspace_id=state["workspace_id"]
            ) as session:
                session_row = (
                    await session.execute(
                        sa.text("SELECT revoked_at FROM sessions WHERE token_hash IS NOT NULL LIMIT 1")
                    )
                ).one()
                run_row = (
                    await session.execute(
                        sa.text("SELECT status, reasons FROM runs WHERE id = :id"),
                        {"id": str(state["run_id"])},
                    )
                ).one()
                execution_row = (
                    await session.execute(
                        sa.text("SELECT status FROM executions WHERE run_id = :id"),
                        {"id": str(state["run_id"])},
                    )
                ).one()
            assert session_row[0] is not None
            assert run_row[0] == "error"
            assert any(reason == "quarantined:restore" for reason in run_row[1])
            assert execution_row[0] == "error"
        finally:
            await async_engine.dispose()
    finally:
        await drop_database(admin, database)


async def test_restore_rejects_damaged_backup(role_engines, test_db, tmp_path: Path) -> None:
    state = await _seed_backup_state(role_engines, tmp_path)
    service = BackupService(admin_dsn(test_db.name), artifact_root=state["store"].root)
    backup_dir = tmp_path / "backup-broken"
    await service.create(backup_dir)
    blob_files = list((backup_dir / "blobs").rglob("*"))
    blob_file = next(path for path in blob_files if path.is_file())
    blob_file.write_bytes(b"tampered")
    database = f"agentqa_test_restore_{secrets.token_hex(4)}"
    with pytest.raises(IntegrityError):
        await service.restore(backup_dir, database=database, migrate_dsn=role_dsn(ROLE_MIGRATE, database))


async def test_keyring_backup_roundtrip_and_missing_key(tmp_path: Path) -> None:
    keyring = MasterKeyring.synthetic()
    target = tmp_path / "keyring" / "master.enc"
    backup_keyring(keyring, target, "passphrase-strong-1")
    restored = restore_keyring(target, "passphrase-strong-1")
    assert restored.current_version == keyring.current_version
    assert restored.key(keyring.current_version) == keyring.key(keyring.current_version)

    with pytest.raises(KeyringRestoreError):
        restore_keyring(tmp_path / "keyring" / "missing.enc", "passphrase-strong-1")
    with pytest.raises(KeyringRestoreError):
        restore_keyring(target, "wrong-passphrase")
    document = json.loads(target.read_text(encoding="utf-8"))
    assert "keys" not in document
    assert document["schema"] == "keyring/1"


async def test_backup_cli_create_verify_and_keyring(role_engines, test_db, tmp_path: Path, monkeypatch, capsys) -> None:
    import asyncio

    from agentqa.platform.backup.cli import main as backup_main

    state = await _seed_backup_state(role_engines, tmp_path)
    monkeypatch.setenv("AGENTQA_ADMIN_DSN", admin_dsn(test_db.name))
    code = await asyncio.to_thread(
        backup_main, ["create", "--artifacts", str(state["store"].root), "--out", str(tmp_path / "cli-backup")]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert json.loads(captured.out)["tables"] > 0
    code = await asyncio.to_thread(backup_main, ["verify", "--backup", str(tmp_path / "cli-backup")])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert json.loads(captured.out)["ok"] is True

    monkeypatch.setenv("AGENTQA_KEYRING_PASSPHRASE", "pass-cli-1")
    assert await asyncio.to_thread(backup_main, ["keyring-backup", "--out", str(tmp_path / "keyring.enc")]) == 0
    capsys.readouterr()
    assert await asyncio.to_thread(backup_main, ["keyring-restore", "--file", str(tmp_path / "keyring.enc")]) == 0
    capsys.readouterr()


async def test_restore_requires_keyring_backup_file(role_engines, test_db, tmp_path: Path) -> None:
    state = await _seed_backup_state(role_engines, tmp_path)
    service = BackupService(admin_dsn(test_db.name), artifact_root=state["store"].root)
    backup_dir = tmp_path / "backup-keyring"
    await service.create(backup_dir)
    with pytest.raises(KeyringRestoreError):
        restore_keyring(backup_dir / "keyring.enc", "any-passphrase")
    _ = uuid4()
