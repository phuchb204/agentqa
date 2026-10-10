from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from agentqa.platform.backup.service import (
    BackupService,
    KeyringRestoreError,
    backup_keyring,
    restore_keyring,
)
from agentqa.platform.security.credentials import MasterKeyring
from agentqa.platform.storage.roles import ROLE_MIGRATE, role_dsn


def _admin_dsn(args: argparse.Namespace) -> str:
    dsn = getattr(args, "admin_dsn", None) or os.environ.get("AGENTQA_ADMIN_DSN")
    if not dsn:
        raise SystemExit("Cần --admin-dsn hoặc AGENTQA_ADMIN_DSN")
    return dsn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentqa.platform.backup")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Tạo backup DB + blob manifest")
    create.add_argument("--admin-dsn")
    create.add_argument("--artifacts", required=True)
    create.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="Kiểm checksum/counts của backup")
    verify.add_argument("--backup", required=True)

    restore = sub.add_parser("restore", help="Restore vào database cô lập")
    restore.add_argument("--admin-dsn")
    restore.add_argument("--artifacts", required=True)
    restore.add_argument("--backup", required=True)
    restore.add_argument("--database", required=True)
    restore.add_argument("--migrate-dsn")

    keyring_backup = sub.add_parser("keyring-backup", help="Backup encrypted keyring")
    keyring_backup.add_argument("--out", required=True)
    keyring_backup.add_argument("--passphrase-env", default="AGENTQA_KEYRING_PASSPHRASE")

    keyring_restore = sub.add_parser("keyring-restore", help="Kiểm keyring restore được")
    keyring_restore.add_argument("--file", required=True)
    keyring_restore.add_argument("--passphrase-env", default="AGENTQA_KEYRING_PASSPHRASE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "keyring-backup":
        passphrase = os.environ.get(args.passphrase_env, "")
        if not passphrase:
            print(f"Thiếu env {args.passphrase_env}", file=sys.stderr)
            return 2
        path = backup_keyring(MasterKeyring.synthetic(), Path(args.out), passphrase)
        print(json.dumps({"keyring_backup": str(path)}))
        return 0
    if args.command == "keyring-restore":
        passphrase = os.environ.get(args.passphrase_env, "")
        try:
            keyring = restore_keyring(Path(args.file), passphrase)
        except KeyringRestoreError as error:
            print(json.dumps({"error": str(error)}), file=sys.stderr)
            return 2
        print(json.dumps({"restored_version": keyring.current_version}))
        return 0
    if args.command == "verify":
        checker = BackupService("postgresql+psycopg://unused", artifact_root=Path("."))
        manifest = checker.verify(Path(args.backup))
        print(json.dumps({"ok": True, "schema_version": manifest.schema_version}))
        return 0
    service = BackupService(_admin_dsn(args), artifact_root=Path(args.artifacts))
    if args.command == "create":
        manifest = asyncio.run(service.create(Path(args.out)))
        print(json.dumps({"schema_version": manifest.schema_version, "tables": len(manifest.table_counts)}))
        return 0
    migrate_dsn = args.migrate_dsn or role_dsn(ROLE_MIGRATE, args.database)
    report = asyncio.run(service.restore(Path(args.backup), database=args.database, migrate_dsn=migrate_dsn))
    print(json.dumps({"database": report.database, "failures": report.failures, "links_ok": report.links_ok}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
