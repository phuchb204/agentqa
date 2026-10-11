from __future__ import annotations

import json
import math
import platform
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from agentqa.platform.storage.database import configure_event_loop_policy, create_engine
from agentqa.platform.storage.migrate import upgrade
from agentqa.platform.storage.roles import (
    APP_ROLES,
    ROLE_MIGRATE,
    admin_dsn,
    bootstrap_profile,
    create_database,
    drop_database,
    role_dsn,
)

WORKLOAD_SCHEMA_VERSION = "workload-report/1"
MANIFEST_SCHEMA_VERSION = "workload-manifest/1"
METRICS_SCHEMA_VERSION = "workload-metrics/1"

DEFAULT_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "W1": {"max_wall_seconds": 180.0},
    "W2": {"max_wall_seconds": 20.0, "max_peak_reserved": 4},
    "W3": {"p95_delivery_seconds": 1.0, "max_wall_seconds": 120.0},
    "W4": {"p95_read_seconds": 0.5, "max_wall_seconds": 300.0},
    "W5": {"max_wall_seconds": 300.0},
    "W6": {"max_wall_seconds": 300.0},
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def p95(values: list[float]) -> float:
    if not values:
        raise ValueError("p95 cần ít nhất một giá trị")
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile cần ít nhất một giá trị")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def host_info() -> dict[str, Any]:
    return {
        "platform": sys.platform,
        "release": platform.release(),
        "python": platform.python_version(),
        "machine": platform.machine(),
    }


def browser_info() -> dict[str, Any]:
    try:
        version = metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return {"engine": "chromium", "playwright_version": None}
    return {"engine": "chromium", "playwright_version": version}


async def db_info(engine: Any) -> dict[str, Any]:
    async with engine.connect() as connection:
        result = await connection.execute(sa.text("SELECT version()"))
        return {"version": str(result.scalar_one())}


@dataclass
class WorkloadContext:
    repo_root: Path
    profile: str
    profile_dir: Path
    database: str
    engines: dict[str, Any]
    thresholds: dict[str, float | int]
    config: dict[str, Any] = field(default_factory=dict)
    started_monotonic: float = 0.0

    @property
    def manifest_path(self) -> Path:
        return self.profile_dir / "manifest.json"

    @property
    def metrics_path(self) -> Path:
        return self.profile_dir / "metrics.json"


async def setup_engines() -> tuple[str, dict[str, Any]]:
    configure_event_loop_policy()
    admin = admin_dsn()
    await bootstrap_profile(admin)
    name = f"agentqa_workload_{secrets.token_hex(4)}"
    await create_database(admin, name)
    await upgrade(role_dsn(ROLE_MIGRATE, name))
    pool_settings = {"pool_size": 10, "max_overflow": 30}
    engines = {role: create_engine(role_dsn(role, name), **pool_settings) for role in APP_ROLES}
    return name, engines


async def close_engines(engines: dict[str, Any], database: str) -> None:
    for engine in engines.values():
        await engine.dispose()
    await drop_database(admin_dsn(), database)


class DsnTable:
    def __init__(self, database: str) -> None:
        self.name = database

    def dsn(self, role: str) -> str:
        return role_dsn(role, self.name)


async def pin_manifest(ctx: WorkloadContext) -> dict[str, Any]:
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "profile": ctx.profile,
        "tool": "run_workloads",
        "models": "fake",
        "config": ctx.config,
        "thresholds": ctx.thresholds,
        "frames": {
            "host": host_info(),
            "browser": browser_info(),
            "database": await db_info(ctx.engines["agentqa_migrate"]),
        },
        "pinned_before_run": True,
        "ok": None,
        "generated_at": now_iso(),
        "metrics_path": f"artifacts/workloads/{ctx.profile}/metrics.json",
    }
    ctx.profile_dir.mkdir(parents=True, exist_ok=True)
    ctx.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def finalize_manifest(ctx: WorkloadContext, *, ok: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    manifest["ok"] = ok
    manifest["finished_at"] = now_iso()
    if extra:
        manifest.update(extra)
    ctx.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def write_metrics(ctx: WorkloadContext, payload: dict[str, Any]) -> dict[str, Any]:
    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "profile": ctx.profile,
        "generated_at": now_iso(),
        "duration_seconds": time.monotonic() - ctx.started_monotonic,
        **payload,
    }
    ctx.metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metrics


def write_failure_artifact(ctx: WorkloadContext, error: BaseException) -> None:
    import traceback

    failure = {
        "schema_version": "workload-failure/1",
        "profile": ctx.profile,
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
        "generated_at": now_iso(),
    }
    (ctx.profile_dir / "failure.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def update_latest(report_dir: Path, repo_root: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(report_dir.glob("W*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        profile = manifest.get("profile", path.parent.name)
        profiles[profile] = {
            "ok": manifest.get("ok") is True,
            "pinned_before_run": manifest.get("pinned_before_run") is True,
            "manifest": path.relative_to(repo_root).as_posix(),
        }
    expected = {"W1", "W2", "W3", "W4", "W5", "W6"}
    latest = {
        "schema_version": "workloads-latest/1",
        "tool": "run_workloads",
        "ok": expected <= set(profiles) and all(item["ok"] for item in profiles.values()),
        "profiles": profiles,
        "run_results": results,
        "generated_at": now_iso(),
    }
    (report_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return latest
