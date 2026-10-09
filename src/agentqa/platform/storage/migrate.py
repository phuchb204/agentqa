from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from agentqa.platform.storage.roles import (
    TEST_BOOTSTRAP_DSN,
    TEST_ROLE_PASSWORD,
    admin_dsn,
    bootstrap_profile,
    create_database,
)

MIGRATION_LOCK_KEY = 0x6167656E74716101
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SCRIPT_LOCATION = REPO_ROOT / "infra" / "migrations"


def build_config(dsn: str, *, script_location: Path | None = None) -> Config:
    location = script_location or Path(DEFAULT_SCRIPT_LOCATION)
    config = Config()
    config.set_main_option("script_location", str(location))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


async def _run_alembic(dsn: str, revision: str, *, downgrade: bool) -> None:
    config = build_config(dsn)
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})

            def run(sync_connection) -> None:
                config.attributes["connection"] = sync_connection
                if downgrade:
                    command.downgrade(config, revision)
                else:
                    command.upgrade(config, revision)

            try:
                await connection.run_sync(run)
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
    finally:
        await engine.dispose()


async def upgrade(dsn: str, revision: str = "head") -> None:
    await _run_alembic(dsn, revision, downgrade=False)


async def downgrade(dsn: str, revision: str = "-1") -> None:
    await _run_alembic(dsn, revision, downgrade=True)


def database_name(dsn: str) -> str:
    name = make_url(dsn).database
    if not name:
        raise SystemExit("DSN phải có tên database")
    return name


async def run(args: argparse.Namespace) -> int:
    if args.command == "bootstrap":
        dsn = args.dsn or admin_dsn()
        await bootstrap_profile(dsn, password=args.password)
        print("bootstrap ok")
        return 0
    if args.command == "upgrade":
        if args.bootstrap:
            await bootstrap_profile(args.admin_dsn or admin_dsn(), password=args.password)
        if args.create_database:
            await create_database(args.admin_dsn or admin_dsn(), database_name(args.dsn))
        await upgrade(args.dsn, args.revision)
        print(f"upgrade to {args.revision} ok")
        return 0
    if args.command == "downgrade":
        await downgrade(args.dsn, args.revision if args.revision != "head" else "-1")
        print(f"downgrade to {args.revision} ok")
        return 0
    raise SystemExit(f"unknown command {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentqa.platform.storage.migrate")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="Tạo roles và oracle database của test profile")
    bootstrap.add_argument("--dsn", default=None)
    bootstrap.add_argument("--password", default=TEST_ROLE_PASSWORD)

    upgrade_parser = sub.add_parser("upgrade", help="Chạy migration lên revision")
    upgrade_parser.add_argument("--dsn", required=True)
    upgrade_parser.add_argument("--revision", default="head")
    upgrade_parser.add_argument("--bootstrap", action="store_true")
    upgrade_parser.add_argument("--create-database", action="store_true")
    upgrade_parser.add_argument("--admin-dsn", default=TEST_BOOTSTRAP_DSN)
    upgrade_parser.add_argument("--password", default=TEST_ROLE_PASSWORD)

    downgrade_parser = sub.add_parser("downgrade", help="Rollback migration")
    downgrade_parser.add_argument("--dsn", required=True)
    downgrade_parser.add_argument("--revision", default="-1")

    return parser


def main(argv: list[str] | None = None) -> int:
    import asyncio

    from agentqa.platform.storage.database import configure_event_loop_policy

    args = build_parser().parse_args(argv)
    configure_event_loop_policy()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
