from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.security.credentials import DATA_KEY_BYTES, MasterKeyring
from agentqa.platform.storage import tables
from agentqa.platform.storage.migrate import alembic_head_revision, upgrade

MANIFEST_NAME = "manifest.json"
DATA_DIR = "data"
BLOB_DIR = "blobs"
TERMINAL_RUNS = ("succeeded", "failed", "cancelled", "error", "inconclusive")


class BackupError(RuntimeError):
    pass


class KeyringRestoreError(BackupError):
    pass


class IntegrityError(BackupError):
    pass


@dataclass(frozen=True)
class BackupManifest:
    schema_version: str
    head_version: str
    table_counts: dict[str, int]
    blobs: dict[str, dict[str, Any]]
    data_files: dict[str, str]
    created_at: str


@dataclass(frozen=True)
class RestoreReport:
    database: str
    schema_version: str
    table_counts: dict[str, int]
    links_ok: bool
    session_revoked: int
    tokens_revoked: int
    runs_quarantined: int
    failures: list[str] = field(default_factory=list)


def _encode(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and "__bytes__" in value:
        return base64.b64decode(value["__bytes__"])
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupService:
    def __init__(self, admin_dsn: str, *, artifact_root: Path) -> None:
        self._admin_dsn = admin_dsn
        self._artifact_root = Path(artifact_root)

    async def create(self, target_dir: Path) -> BackupManifest:
        target = Path(target_dir)
        data_dir = target / DATA_DIR
        blob_dir = target / BLOB_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        blob_dir.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(self._admin_dsn)
        table_counts: dict[str, int] = {}
        data_files: dict[str, str] = {}
        try:
            async with engine.connect() as connection:
                schema_version = (
                    await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
                for table in tables.metadata.sorted_tables:
                    exists = (
                        await connection.execute(sa.text("SELECT to_regclass(:name)"), {"name": f"public.{table.name}"})
                    ).scalar_one()
                    if exists is None:
                        continue
                    rows = (await connection.execute(sa.select(table))).mappings().all()
                    path = data_dir / f"{table.name}.jsonl"
                    with path.open("w", encoding="utf-8") as handle:
                        for row in rows:
                            handle.write(
                                json.dumps(
                                    {key: _encode(value) for key, value in row.items()},
                                    ensure_ascii=False,
                                    sort_keys=True,
                                )
                                + "\n"
                            )
                    table_counts[table.name] = len(rows)
                    data_files[table.name] = _sha256_file(path)
        finally:
            await engine.dispose()

        blobs: dict[str, dict[str, Any]] = {}
        if self._artifact_root.is_dir():
            for path in self._artifact_root.rglob("*"):
                if not path.is_file():
                    continue
                key = path.relative_to(self._artifact_root).as_posix()
                payload = path.read_bytes()
                blobs[key] = {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
                destination = blob_dir / Path(*key.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)

        manifest = BackupManifest(
            schema_version=schema_version,
            head_version=alembic_head_revision(),
            table_counts=table_counts,
            blobs=blobs,
            data_files=data_files,
            created_at=datetime.now(UTC).isoformat(),
        )
        (target / MANIFEST_NAME).write_text(
            json.dumps(manifest.__dict__, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return manifest

    def verify(self, backup_dir: Path) -> BackupManifest:
        target = Path(backup_dir)
        manifest_path = target / MANIFEST_NAME
        if not manifest_path.is_file():
            raise BackupError(f"Thiếu manifest tại {manifest_path}")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = BackupManifest(**raw)
        failures: list[str] = []
        for table, expected in manifest.data_files.items():
            path = target / DATA_DIR / f"{table}.jsonl"
            if not path.is_file() or _sha256_file(path) != expected:
                failures.append(f"data:{table}")
        for key, info in manifest.blobs.items():
            path = target / BLOB_DIR / Path(*key.split("/"))
            if not path.is_file():
                failures.append(f"blob_missing:{key}")
                continue
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != info["sha256"] or len(payload) != info["size"]:
                failures.append(f"blob_digest:{key}")
        if failures:
            raise IntegrityError("Backup hỏng: " + ", ".join(sorted(failures)))
        head = alembic_head_revision()
        if manifest.head_version != head:
            raise IntegrityError(f"Schema version backup ({manifest.head_version}) khác head hiện tại ({head})")
        return manifest

    async def restore(
        self,
        backup_dir: Path,
        *,
        database: str,
        migrate_dsn: str,
        admin_dsn: str | None = None,
    ) -> RestoreReport:
        from sqlalchemy.engine import make_url

        from agentqa.platform.storage.roles import create_database

        manifest = self.verify(backup_dir)
        target = Path(backup_dir)
        admin = admin_dsn or self._admin_dsn
        await create_database(admin, database)
        await upgrade(migrate_dsn)
        target_dsn = make_url(self._admin_dsn).set(database=database).render_as_string(hide_password=False)
        engine = create_async_engine(target_dsn)
        failures: list[str] = []
        restored_counts: dict[str, int] = {}
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text("SET session_replication_role = replica"))
                for table in tables.metadata.sorted_tables:
                    path = target / DATA_DIR / f"{table.name}.jsonl"
                    if not path.is_file():
                        restored_counts[table.name] = 0
                        continue
                    rows: list[dict[str, Any]] = []
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            rows.append({key: _decode(value) for key, value in json.loads(line).items()})
                    if rows:
                        await connection.execute(table.insert(), rows)
                    restored_counts[table.name] = len(rows)
                await connection.execute(sa.text("SET session_replication_role = DEFAULT"))
                revoked_sessions = (
                    await connection.execute(
                        sa.text("UPDATE sessions SET revoked_at = now() WHERE revoked_at IS NULL RETURNING id")
                    )
                ).all()
                revoked_tokens = (
                    await connection.execute(
                        sa.text(
                            "UPDATE api_tokens SET revoked_at = now(), revoke_reason = 'restore_policy' "
                            "WHERE revoked_at IS NULL RETURNING id"
                        )
                    )
                ).all()
                quarantined = (
                    await connection.execute(
                        sa.text(
                            "UPDATE runs SET status = 'error', "
                            "reasons = reasons || to_jsonb(ARRAY['quarantined:restore']::text[]), "
                            "finalized_at = now(), updated_at = now() "
                            "WHERE status <> ALL(:terminal) RETURNING id"
                        ),
                        {"terminal": list(TERMINAL_RUNS)},
                    )
                ).all()
                await connection.execute(
                    sa.text(
                        "UPDATE executions SET status = 'error', updated_at = now() WHERE status <> ALL(:terminal)"
                    ),
                    {"terminal": list(TERMINAL_RUNS)},
                )
                await connection.execute(
                    sa.text(
                        "UPDATE jobs SET state = 'quarantined', updated_at = now() "
                        "WHERE state IN ('queued', 'claimed', 'running', 'waiting', 'settling')"
                    )
                )
        finally:
            await engine.dispose()

        for table, expected in manifest.table_counts.items():
            actual = restored_counts.get(table)
            if actual != expected:
                failures.append(f"count:{table}:{actual}!={expected}")

        links_ok = True
        link_engine = create_async_engine(target_dsn)
        try:
            async with link_engine.connect() as connection:
                rows = (
                    (
                        await connection.execute(
                            sa.text("SELECT object_key, digest FROM artifacts WHERE object_key IS NOT NULL")
                        )
                    )
                    .mappings()
                    .all()
                )
        finally:
            await link_engine.dispose()
        for row in rows:
            info = manifest.blobs.get(row["object_key"])
            if info is None or (row["digest"] and row["digest"] != info["sha256"]):
                links_ok = False
                failures.append(f"link:{row['object_key']}")

        return RestoreReport(
            database=database,
            schema_version=manifest.schema_version,
            table_counts=restored_counts,
            links_ok=links_ok,
            session_revoked=len(revoked_sessions),
            tokens_revoked=len(revoked_tokens),
            runs_quarantined=len(quarantined),
            failures=failures,
        )


def backup_keyring(keyring: MasterKeyring, target_file: Path, passphrase: str) -> Path:
    if not passphrase:
        raise KeyringRestoreError("Passphrase rỗng không được phép")
    material = {
        "current_version": keyring.current_version,
        "keys": {str(version): base64.b64encode(key).decode("ascii") for version, key in keyring._keys.items()},
    }
    plaintext = json.dumps(material, sort_keys=True).encode("utf-8")
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000, dklen=DATA_KEY_BYTES)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"agentqa-keyring/1")
    path = Path(target_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "keyring/1",
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def restore_keyring(source_file: Path, passphrase: str) -> MasterKeyring:
    path = Path(source_file)
    if not path.is_file():
        raise KeyringRestoreError(f"Thiếu keyring backup: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    salt = base64.b64decode(document["salt"])
    nonce = base64.b64decode(document["nonce"])
    ciphertext = base64.b64decode(document["ciphertext"])
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000, dklen=DATA_KEY_BYTES)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, b"agentqa-keyring/1")
    except Exception as error:
        raise KeyringRestoreError("Không giải mã được keyring (sai passphrase hoặc file hỏng)") from error
    material = json.loads(plaintext)
    keys = {int(version): base64.b64decode(value) for version, value in material["keys"].items()}
    return MasterKeyring(keys, current_version=int(material["current_version"]))
