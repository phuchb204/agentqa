from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from oracle.registry import ORACLE_VERSION, RECORDS, registry_digest

CREATE_TABLE = sa.text(
    """
    CREATE TABLE IF NOT EXISTS oracle_records (
        logical_key text PRIMARY KEY,
        app text NOT NULL,
        version integer NOT NULL,
        payload jsonb NOT NULL,
        payload_digest text NOT NULL,
        registry_digest text NOT NULL,
        published_at timestamptz NOT NULL DEFAULT now()
    )
    """
)

UPSERT = sa.text(
    """
    INSERT INTO oracle_records (logical_key, app, version, payload, payload_digest, registry_digest)
    VALUES (:logical_key, :app, :version, CAST(:payload AS jsonb), :payload_digest, :registry_digest)
    ON CONFLICT (logical_key) DO UPDATE SET
        app = EXCLUDED.app,
        version = EXCLUDED.version,
        payload = EXCLUDED.payload,
        payload_digest = EXCLUDED.payload_digest,
        registry_digest = EXCLUDED.registry_digest,
        published_at = now()
    """
)


async def publish_records(dsn: str) -> int:
    registry_digest_value = registry_digest()
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(CREATE_TABLE)
            for logical_key in sorted(RECORDS):
                record = RECORDS[logical_key]
                payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
                await connection.execute(
                    UPSERT,
                    {
                        "logical_key": logical_key,
                        "app": record["app"],
                        "version": ORACLE_VERSION,
                        "payload": payload,
                        "payload_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                        "registry_digest": registry_digest_value,
                    },
                )
    finally:
        await engine.dispose()
    return len(RECORDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oracle.publish", description="Publish oracle records vào agentqa_oracle")
    parser.add_argument("--dsn", required=True, help="DSN role agentqa_evaluator tới agentqa_oracle")
    args = parser.parse_args(argv)
    count = asyncio.run(publish_records(args.dsn))
    print(json.dumps({"published": count, "registry_digest": registry_digest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
