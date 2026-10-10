from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import signal
import sys
from uuid import UUID

from agentqa.platform.health import HealthService
from agentqa.platform.scheduler.service import SchedulerService
from agentqa.platform.storage.database import configure_event_loop_policy, create_engine
from agentqa.platform.storage.roles import ROLE_API

DEFAULT_INTERVAL_SECONDS = 60.0


class SchedulerDaemon:
    def __init__(
        self,
        *,
        dsn: str,
        workspace_id: UUID,
        principal_id: UUID,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        worker_id: str = "scheduler-daemon",
    ) -> None:
        self._engine = create_engine(dsn)
        self._scheduler = SchedulerService(self._engine)
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._interval = interval_seconds
        self._worker_id = worker_id
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self._engine.dispose()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            health = HealthService({ROLE_API: self._engine})
            schema = await health.check_schema()
            if not schema.ok:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                continue
            try:
                await self._scheduler.materialize_due(workspace_id=self._workspace_id, principal_id=self._principal_id)
                await self._scheduler.claim_due(
                    workspace_id=self._workspace_id,
                    principal_id=self._principal_id,
                    worker_id=self._worker_id,
                )
            except Exception:
                pass
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)


def _env_uuid(name: str) -> UUID:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Thiếu biến môi trường {name}")
    return UUID(value)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    configure_event_loop_policy()
    dsn = os.environ.get("AGENTQA_SCHEDULER_DSN") or os.environ.get("AGENTQA_DSN")
    if not dsn:
        raise SystemExit("Thiếu AGENTQA_SCHEDULER_DSN/AGENTQA_DSN")
    daemon = SchedulerDaemon(
        dsn=dsn,
        workspace_id=_env_uuid("AGENTQA_WORKSPACE_ID"),
        principal_id=_env_uuid("AGENTQA_PRINCIPAL_ID"),
        interval_seconds=float(os.environ.get("AGENTQA_SCHEDULER_INTERVAL", DEFAULT_INTERVAL_SECONDS)),
        worker_id=os.environ.get("AGENTQA_SCHEDULER_ID", f"scheduler-{secrets.token_hex(4)}"),
    )

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            signal_value = getattr(signal, signame, None)
            if signal_value is not None:
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(signal_value, daemon.request_stop)
        try:
            await daemon.run_forever()
        finally:
            await daemon.close()

    asyncio.run(runner())
    return 0


if __name__ == "__main__":
    sys.exit(main())
