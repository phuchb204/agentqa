from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.platform.health import HealthService
from agentqa.platform.queue import JobQueue
from agentqa.platform.runs.coordinator import ExecutionOutcome, ExecutionSpec, RunEventRecorder, outcome_from_dict
from agentqa.platform.runs.worker import RunWorker
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_engine, create_session_factory
from agentqa.platform.storage.roles import ROLE_API, ROLE_SUPERVISOR, ROLE_WORKER
from agentqa.platform.storage.scope import set_scope

POLL_SECONDS = 2.0
SUPERVISOR_START_TIMEOUT = 180.0
QUARANTINE_REASON = "restart_quarantine"


class SupervisorClient:
    def __init__(self, port: int, token: str, *, timeout: float = 300.0) -> None:
        self._socket = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._file = self._socket.makefile("rwb")
        self._socket.settimeout(timeout)
        hello = self._exchange({"token": token})
        if hello.get("ok") is not True:
            raise RuntimeError(f"supervisor từ chối token: {hello}")

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise ConnectionError("supervisor đóng kết nối")
        return json.loads(line.decode("utf-8"))

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._exchange(payload)

    def close_socket(self) -> None:
        with contextlib.suppress(OSError):
            self._socket.close()


class LocalSupervisor:
    def __init__(
        self,
        *,
        supervisor_dsn: str,
        workspace_id: UUID,
        principal_id: UUID,
        fixture_base_url: str = "",
        fixture_control_token: str = "",
        fixture_origin: str = "",
        workspace_root: str | None = None,
    ) -> None:
        self._token = secrets.token_urlsafe(16)
        command = [
            sys.executable,
            "-m",
            "agentqa.platform.supervisor.entrypoint",
            "--dsn",
            supervisor_dsn,
            "--workspace-id",
            str(workspace_id),
            "--principal-id",
            str(principal_id),
            "--supervisor-id",
            "daemon-supervisor",
            "--control-token",
            self._token,
            "--port",
            "0",
        ]
        if fixture_base_url:
            command.extend(["--fixture-base-url", fixture_base_url])
        if fixture_control_token:
            command.extend(["--fixture-control-token", fixture_control_token])
        if fixture_origin:
            command.append(f"--allow-origin={fixture_origin}")
        environment = {**os.environ, "AGENTQA_WORKSPACE_ROOT": workspace_root or os.getcwd()}
        self._process = subprocess.Popen(
            command,
            cwd=workspace_root or os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr is not None else ""
            raise RuntimeError(f"supervisor không khởi động: {stderr[-2000:]}")
        self.port = int(json.loads(line)["port"])

    @property
    def token(self) -> str:
        return self._token

    def stop(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)


class RemoteCoordinator:
    def __init__(self, supervisor: LocalSupervisor) -> None:
        self._supervisor = supervisor

    async def execute(self, spec: ExecutionSpec) -> ExecutionOutcome:
        return await asyncio.to_thread(self._execute_sync, spec)

    def _execute_sync(self, spec: ExecutionSpec) -> ExecutionOutcome:
        client = SupervisorClient(self._supervisor.port, self._supervisor.token)
        try:
            payload: dict[str, Any] = {
                "op": "run_execution",
                "workspace_id": str(spec.workspace_id),
                "principal_id": str(spec.principal_id),
                "run_id": str(spec.run_id),
                "execution_id": str(spec.execution_id),
                "attempt_id": str(spec.attempt_id),
                "logical_key": spec.logical_key,
                "case": spec.case.model_dump(mode="json"),
                "target_base_url": spec.target_base_url,
                "fixture_ref": spec.fixture_ref,
                "namespace": spec.namespace,
                "fixture_seed": spec.fixture_seed,
                "parameters": spec.parameters,
                "gate_profile": spec.gate_profile,
                "fence_epoch": spec.fence_epoch,
                "policy": spec.policy,
                "observation_mode": spec.observation_mode,
                "snapshot_digest": spec.snapshot_digest,
                "provisional": spec.provisional,
            }
            if spec.case_id is not None:
                payload["case_id"] = str(spec.case_id)
            if spec.case_revision_id is not None:
                payload["case_revision_id"] = str(spec.case_revision_id)
            response = client.request(payload)
        finally:
            client.close_socket()
        if response.get("ok") is not True:
            raise RuntimeError(f"supervisor lỗi: {response}")
        return outcome_from_dict(response["result"])

    async def apply_control(self, control_id: UUID) -> dict[str, Any]:
        return {}


class WorkerDaemon:
    def __init__(
        self,
        *,
        dsn_by_role: dict[str, str],
        workspace_id: UUID,
        principal_id: UUID,
        worker_id: str = "worker-daemon",
        fixture_base_url: str = "",
        fixture_control_token: str = "",
        fixture_origin: str = "",
        poll_seconds: float = POLL_SECONDS,
        maintenance_only: bool = False,
    ) -> None:
        self._dsn_by_role = dsn_by_role
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._worker_id = worker_id
        self._fixture_base_url = fixture_base_url
        self._fixture_control_token = fixture_control_token
        self._fixture_origin = fixture_origin
        self._poll_seconds = poll_seconds
        self._maintenance_only = maintenance_only
        self._stop = asyncio.Event()
        self._supervisor: LocalSupervisor | None = None
        self._worker: RunWorker | None = None
        self._engine: AsyncEngine | None = None

    def request_stop(self) -> None:
        self._stop.set()

    async def start(self) -> None:
        self._engine = create_engine(self._dsn_by_role[ROLE_WORKER])
        if self._maintenance_only:
            return
        self._supervisor = LocalSupervisor(
            supervisor_dsn=self._dsn_by_role[ROLE_SUPERVISOR],
            workspace_id=self._workspace_id,
            principal_id=self._principal_id,
            fixture_base_url=self._fixture_base_url,
            fixture_control_token=self._fixture_control_token,
            fixture_origin=self._fixture_origin,
            workspace_root=os.environ.get("AGENTQA_WORKSPACE_ROOT"),
        )
        queue = JobQueue(
            create_session_factory(self._engine),
            workspace_id=self._workspace_id,
            principal_id=self._principal_id,
        )
        self._worker = RunWorker(
            queue=queue,
            coordinator=RemoteCoordinator(self._supervisor),
            recorder=RunEventRecorder(self._engine),
            engine=self._engine,
            principal_id=self._principal_id,
            workspace_id=self._workspace_id,
            worker_id=self._worker_id,
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._supervisor is not None:
            self._supervisor.stop()
            self._supervisor = None

    async def schema_ready(self) -> bool:
        assert self._engine is not None
        health = HealthService({ROLE_API: self._engine})
        report = await health.check_schema()
        return report.ok

    async def quarantine_stale(self, *, reason: str = QUARANTINE_REASON) -> list[UUID]:
        assert self._engine is not None
        factory = create_session_factory(self._engine)
        quarantined: list[UUID] = []
        async with factory() as session, session.begin():
            await set_scope(session, principal_id=self._principal_id, workspace_id=self._workspace_id)
            stale = (
                await session.execute(
                    sa.select(tables.worker_leases.c.id, tables.worker_leases.c.job_id, tables.jobs.c.run_id)
                    .join(tables.jobs, tables.jobs.c.id == tables.worker_leases.c.job_id)
                    .where(
                        tables.worker_leases.c.workspace_id == self._workspace_id,
                        tables.worker_leases.c.released_at.is_(None),
                        tables.worker_leases.c.expires_at < sa.func.now(),
                    )
                )
            ).all()
            for lease in stale:
                await session.execute(
                    sa.update(tables.worker_leases)
                    .where(tables.worker_leases.c.id == lease.id)
                    .values(released_at=sa.func.now())
                )
                await session.execute(
                    sa.update(tables.jobs)
                    .where(tables.jobs.c.id == lease.job_id)
                    .values(
                        state="quarantined",
                        claimed_by=None,
                        updated_at=sa.func.now(),
                        payload=sa.func.jsonb_set(
                            tables.jobs.c.payload,
                            sa.cast(sa.literal("{quarantine_reason}"), sa.dialects.postgresql.ARRAY(sa.Text)),
                            sa.func.to_jsonb(sa.literal(reason)),
                        ),
                    )
                )
                if lease.run_id is not None:
                    await session.execute(
                        sa.update(tables.runs)
                        .where(tables.runs.c.id == lease.run_id)
                        .values(
                            status="error",
                            reasons=sa.text("reasons || to_jsonb(ARRAY['quarantined:" + reason + "']::text[])"),
                            finalized_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )
                    await session.execute(
                        sa.update(tables.executions)
                        .where(
                            tables.executions.c.run_id == lease.run_id,
                            tables.executions.c.status.in_(("queued", "running", "waiting")),
                        )
                        .values(status="error", updated_at=datetime.now(UTC))
                    )
                quarantined.append(lease.job_id)
        return quarantined

    async def run_forever(self) -> None:
        if not await self.schema_ready():
            await self.quarantine_stale(reason="version_mismatch")
        while not self._stop.is_set():
            if not await self.schema_ready():
                await self.quarantine_stale(reason="version_mismatch")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                continue
            if self._worker is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                continue
            summary = await self._worker.run_once()
            if summary is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)

    async def drain(self) -> None:
        self.request_stop()


def _env_uuid(name: str) -> UUID:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Thiếu biến môi trường {name}")
    return UUID(value)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    from agentqa.platform.storage.database import configure_event_loop_policy

    configure_event_loop_policy()
    dsn = os.environ.get("AGENTQA_DSN")
    supervisor_dsn = os.environ.get("AGENTQA_SUPERVISOR_DSN", dsn)
    if not dsn or not supervisor_dsn:
        raise SystemExit("Thiếu AGENTQA_DSN/AGENTQA_SUPERVISOR_DSN")
    workspace_id = _env_uuid("AGENTQA_WORKSPACE_ID")
    principal_id = _env_uuid("AGENTQA_PRINCIPAL_ID")
    daemon = WorkerDaemon(
        dsn_by_role={ROLE_WORKER: dsn, ROLE_SUPERVISOR: supervisor_dsn, ROLE_API: dsn},
        workspace_id=workspace_id,
        principal_id=principal_id,
        worker_id=os.environ.get("AGENTQA_WORKER_ID", f"worker-{secrets.token_hex(4)}"),
        fixture_base_url=os.environ.get("AGENTQA_FIXTURE_BASE_URL", ""),
        fixture_control_token=os.environ.get("AGENTQA_FIXTURE_CONTROL_TOKEN", ""),
        fixture_origin=os.environ.get("AGENTQA_FIXTURE_ORIGIN", ""),
        maintenance_only=os.environ.get("AGENTQA_WORKER_MAINTENANCE_ONLY", "") == "1",
    )

    async def runner() -> None:
        await daemon.start()
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
