from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.storage.migrate import alembic_head_revision
from agentqa.platform.storage.roles import ROLE_API


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: list[CheckResult] = field(default_factory=list)


class HealthService:
    def __init__(
        self,
        engines: Mapping[str, AsyncEngine],
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self._engines = dict(engines)
        self._artifact_root = artifact_root

    async def ready(self) -> ReadinessReport:
        checks: list[CheckResult] = []
        checks.append(await self.check_database())
        checks.append(await self.check_schema())
        checks.append(await self.check_storage())
        checks.append(await self.check_queue())
        checks.append(
            CheckResult(
                name="providers",
                ok=True,
                detail="capability chưa kiểm trong readiness; không gọi model",
            )
        )
        ready = all(check.ok for check in checks if check.name in ("database", "schema", "storage", "queue"))
        return ReadinessReport(ready=ready, checks=checks)

    async def check_database(self) -> CheckResult:
        engine = self._engines.get(ROLE_API)
        if engine is None:
            return CheckResult(name="database", ok=False, detail="api engine chưa cấu hình")
        try:
            async with engine.connect() as connection:
                value = (await connection.execute(sa.select(sa.literal(1)))).scalar_one()
            return CheckResult(name="database", ok=value == 1, detail="ok" if value == 1 else "unexpected")
        except Exception as error:
            return CheckResult(name="database", ok=False, detail=type(error).__name__)

    async def check_schema(self) -> CheckResult:
        engine = self._engines.get(ROLE_API)
        if engine is None:
            return CheckResult(name="schema", ok=False, detail="api engine chưa cấu hình")
        try:
            head = alembic_head_revision()
            async with engine.connect() as connection:
                current = (
                    await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
            ok = current == head
            return CheckResult(
                name="schema",
                ok=ok,
                detail="ok" if ok else f"lệch revision (current={current}, head={head})",
            )
        except Exception as error:
            return CheckResult(name="schema", ok=False, detail=type(error).__name__)

    async def check_storage(self) -> CheckResult:
        root = self._artifact_root
        if root is None:
            return CheckResult(name="storage", ok=False, detail="artifact root chưa cấu hình")
        probe = root / f".readiness-{os.getpid()}"
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return CheckResult(name="storage", ok=True, detail="ok")
        except OSError as error:
            return CheckResult(name="storage", ok=False, detail=type(error).__name__)

    async def check_queue(self) -> CheckResult:
        engine = self._engines.get(ROLE_API)
        if engine is None:
            return CheckResult(name="queue", ok=False, detail="api engine chưa cấu hình")
        try:
            from agentqa.platform.storage import tables

            async with engine.connect() as connection:
                await connection.execute(sa.select(sa.func.count()).select_from(tables.jobs))
            return CheckResult(name="queue", ok=True, detail="ok")
        except Exception as error:
            return CheckResult(name="queue", ok=False, detail=type(error).__name__)
