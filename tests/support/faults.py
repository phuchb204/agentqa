from __future__ import annotations

import contextlib
import json
import os
import queue as queue_module
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.actions import ActionOutcome, ActionReceipt, ActionState, SideEffectClass
from agentqa.platform.controls import ControlService
from agentqa.platform.queue import JobQueue
from agentqa.platform.recovery import RecoveryService
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.roles import ROLE_SUPERVISOR, ROLE_WORKER
from agentqa.platform.supervisor import CommandJournal
from agentqa.platform.supervisor.commands import CommandRequest
from tests.support.postgres import seed_attempt, seed_execution, seed_job, seed_run, seed_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL_SETTING = "agentqa.principal_id"
WORKSPACE_SETTING = "agentqa.workspace_id"


@dataclass
class FaultEnv:
    user_id: UUID
    workspace_id: UUID
    run_id: UUID
    execution_id: UUID
    attempt_id: UUID
    job_id: UUID
    supervisor_dsn: str
    worker_dsn: str
    engines: dict[str, AsyncEngine]
    journal: CommandJournal
    queue: JobQueue
    controls: ControlService
    recovery: RecoveryService


async def build_fault_env(engines: dict[str, AsyncEngine], supervisor_dsn: str, worker_dsn: str) -> FaultEnv:
    user_id, workspace_id = await seed_workspace(engines, label=f"faults-{uuid4().hex[:8]}")
    run_id = await seed_run(engines, principal_id=user_id, workspace_id=workspace_id)
    execution_id = await seed_execution(engines, principal_id=user_id, workspace_id=workspace_id, run_id=run_id)
    attempt_id = await seed_attempt(engines, principal_id=user_id, workspace_id=workspace_id, execution_id=execution_id)
    job_id = await seed_job(
        engines, principal_id=user_id, workspace_id=workspace_id, run_id=run_id, execution_id=execution_id
    )
    supervisor_factory = create_session_factory(engines[ROLE_SUPERVISOR])
    worker_factory = create_session_factory(engines[ROLE_WORKER])
    journal = CommandJournal(
        supervisor_factory,
        workspace_id=workspace_id,
        principal_id=user_id,
        supervisor_id="sup-1",
    )
    queue = JobQueue(worker_factory, workspace_id=workspace_id, principal_id=user_id, slot_capacity=1)
    controls = ControlService(supervisor_factory, workspace_id=workspace_id, principal_id=user_id)
    recovery = RecoveryService(
        supervisor_factory,
        journal,
        workspace_id=workspace_id,
        principal_id=user_id,
    )
    return FaultEnv(
        user_id=user_id,
        workspace_id=workspace_id,
        run_id=run_id,
        execution_id=execution_id,
        attempt_id=attempt_id,
        job_id=job_id,
        supervisor_dsn=supervisor_dsn,
        worker_dsn=worker_dsn,
        engines=engines,
        journal=journal,
        queue=queue,
        controls=controls,
        recovery=recovery,
    )


def literal(value: Any) -> dict[str, Any]:
    return {"kind": "literal", "value": value}


def execute_fields(
    env: FaultEnv,
    *,
    session_key: str,
    command_id: UUID | None = None,
    operation: str = "navigate",
    payload: dict[str, Any] | None = None,
    fence_epoch: int = 1,
    control_revision: int = 0,
    expected_observation_version: int = 1,
    side_effect: str = "read",
) -> dict[str, Any]:
    return {
        "command_id": str(command_id or uuid4()),
        "session_key": session_key,
        "run_id": str(env.run_id),
        "attempt_id": str(env.attempt_id),
        "fence_epoch": fence_epoch,
        "control_revision": control_revision,
        "expected_observation_version": expected_observation_version,
        "operation": operation,
        "payload": payload or {"value": literal("about:blank")},
        "side_effect": side_effect,
    }


def command_request(
    env: FaultEnv,
    *,
    session_key: str,
    command_id: UUID | None = None,
    operation: str = "navigate",
    payload: dict[str, Any] | None = None,
    fence_epoch: int = 1,
    control_revision: int = 0,
    expected_observation_version: int = 1,
    side_effect: str = "read",
) -> CommandRequest:
    return CommandRequest(
        command_id=command_id or uuid4(),
        session_key=session_key,
        run_id=env.run_id,
        attempt_id=env.attempt_id,
        fence_epoch=fence_epoch,
        control_revision=control_revision,
        expected_observation_version=expected_observation_version,
        operation=operation,
        payload=payload or {"value": {"kind": "literal", "value": "about:blank"}},
        side_effect=side_effect,
    )


class FakeExecutor:
    def __init__(self, outcome: ActionOutcome = ActionOutcome.SUCCEEDED, delay: float = 0.0) -> None:
        self.outcome = outcome
        self.delay = delay
        self.calls: list[UUID] = []

    async def dispatch(self, command: Any) -> ActionReceipt:
        self.calls.append(command.command_id)
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        return ActionReceipt(
            command_id=command.command_id,
            state=ActionState.ACCEPTED,
            outcome=self.outcome,
            side_effect=SideEffectClass.READ,
            evidence_refs=["fake:ok"],
            recorded_at=datetime.now(UTC),
        )


def dsn_plain(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://")


def scoped_rows(dsn: str, workspace_id: UUID, principal_id: UUID, sql: str, params: tuple | None = None) -> list[tuple]:
    with psycopg.connect(dsn_plain(dsn), autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"SELECT set_config('{PRINCIPAL_SETTING}', %s, false), set_config('{WORKSPACE_SETTING}', %s, false)",
            (str(principal_id), str(workspace_id)),
        )
        cursor.execute(sql, params or ())
        return [tuple(row) for row in cursor.fetchall()]


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@dataclass
class SupervisorProcess:
    process: subprocess.Popen
    port: int
    token: str
    session_key: str
    attempt_id: UUID
    dsn: str
    workspace_id: UUID
    principal_id: UUID
    stdout_lines: queue_module.Queue = field(default_factory=queue_module.Queue)

    def client(self, timeout: float = 60.0) -> SupervisorClient:
        return SupervisorClient(self.port, self.token, timeout=timeout)

    def kill(self) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            import signal

            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
        self.process.wait(timeout=10)

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def stderr_text(self) -> str:
        if self.process.stderr is None:
            return ""
        try:
            return self.process.stderr.read() or ""
        except (OSError, ValueError):
            return ""


class SupervisorClient:
    def __init__(self, port: int, token: str, *, timeout: float = 60.0) -> None:
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._file = self._sock.makefile("rwb")
        self._sock.settimeout(timeout)
        hello = self._exchange({"token": token})
        assert hello.get("ok") is True, hello

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise ConnectionError("supervisor đóng kết nối")
        return json.loads(line.decode("utf-8"))

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._exchange(payload)

    def send_without_reading(self, payload: dict[str, Any]) -> None:
        self._file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self._file.flush()

    def close_socket(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()

    def open_session(
        self,
        *,
        session_key: str,
        run_id: UUID,
        attempt_id: UUID,
        fence_epoch: int = 1,
    ) -> dict[str, Any]:
        response = self.request(
            {
                "op": "open_session",
                "session_key": session_key,
                "run_id": str(run_id),
                "attempt_id": str(attempt_id),
                "fence_epoch": fence_epoch,
            }
        )
        assert response.get("ok") is True, response
        return response["result"]

    def execute(self, **fields: Any) -> dict[str, Any]:
        response = self.request({"op": "execute", **fields})
        assert response.get("ok") is True, response
        return response["result"]

    def heartbeat(self, session_key: str) -> bool:
        response = self.request({"op": "heartbeat", "session_key": session_key})
        assert response.get("ok") is True, response
        return bool(response["result"]["alive"])

    def close(self) -> None:
        self.request({"op": "close_session", "session_key": "n/a"})
        self.close_socket()


def start_supervisor(
    *,
    dsn: str,
    workspace_id: UUID,
    principal_id: UUID,
    run_id: UUID,
    attempt_id: UUID,
    session_key: str,
    allow_origins: list[str],
    lease_seconds: float = 30.0,
    fence_epoch: int = 1,
    supervisor_id: str = "sup-proc",
    extra_args: list[str] | None = None,
) -> SupervisorProcess:
    token = secrets.token_urlsafe(16)
    command = [
        sys.executable,
        "-m",
        "agentqa.platform.supervisor.entrypoint",
        "--dsn",
        dsn,
        "--workspace-id",
        str(workspace_id),
        "--principal-id",
        str(principal_id),
        "--supervisor-id",
        supervisor_id,
        "--fence-epoch",
        str(fence_epoch),
        "--lease-seconds",
        str(lease_seconds),
        f"--control-token={token}",
        "--port",
        "0",
    ]
    for origin in allow_origins:
        command.extend(["--allow-origin", origin])
    if extra_args:
        command.extend(extra_args)
    environment = {**os.environ, "AGENTQA_WORKSPACE_ROOT": str(REPO_ROOT)}
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        creationflags=creationflags,
        start_new_session=sys.platform != "win32",
    )
    lines: queue_module.Queue = queue_module.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=pump, name="supervisor-stdout", daemon=True).start()
    try:
        startup = lines.get(timeout=180)
    except queue_module.Empty as exc:
        stderr_text = ""
        if process.stderr is not None:
            try:
                stderr_text = process.stderr.read() or ""
            except (OSError, ValueError):
                stderr_text = "<stderr không đọc được>"
        raise RuntimeError(f"supervisor không khởi động được (exit={process.poll()}): {stderr_text[-4000:]}") from exc
    payload = json.loads(startup)
    return SupervisorProcess(
        process=process,
        port=int(payload["port"]),
        token=token,
        session_key=session_key,
        attempt_id=attempt_id,
        dsn=dsn,
        workspace_id=workspace_id,
        principal_id=principal_id,
        stdout_lines=lines,
    )
