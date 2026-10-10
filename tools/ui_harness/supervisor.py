from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SupervisorProcess:
    process: subprocess.Popen
    port: int
    token: str

    def client(self, timeout: float = 60.0) -> SupervisorClient:
        return SupervisorClient(self.port, self.token, timeout=timeout)

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


class SupervisorClient:
    def __init__(self, port: int, token: str, *, timeout: float = 60.0) -> None:
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._file = self._sock.makefile("rwb")
        self._sock.settimeout(timeout)
        hello = self._exchange({"token": token})
        if hello.get("ok") is not True:
            raise RuntimeError(f"supervisor handshake thất bại: {hello}")

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
            self._sock.close()


def sanitized_environment() -> dict[str, str]:
    kept: dict[str, str] = {}
    for name, value in os.environ.items():
        if name.startswith("AGENTQA_") and not name.startswith("AGENTQA_TEST_"):
            continue
        kept[name] = value
    return kept


def start_supervisor(
    *,
    dsn: str,
    workspace_id: UUID,
    principal_id: UUID,
    taskboard_base_url: str,
    taskboard_control_token: str,
    lease_seconds: float = 300.0,
) -> SupervisorProcess:
    token = secrets.token_urlsafe(16)
    parts = taskboard_base_url.split("//", 1)[1]
    host, port_text = parts.split(":", 1)
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
        "ui-e2e-sup",
        "--fence-epoch",
        "1",
        "--lease-seconds",
        str(lease_seconds),
        f"--control-token={token}",
        "--port",
        "0",
        "--allow-origin",
        f"{host}:{port_text}",
        f"--fixture-base-url={taskboard_base_url}",
        f"--fixture-control-token={taskboard_control_token}",
    ]
    environment = {**sanitized_environment(), "AGENTQA_WORKSPACE_ROOT": str(REPO_ROOT)}
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
    assert process.stdout is not None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            payload = json.loads(line)
            return SupervisorProcess(process=process, port=int(payload["port"]), token=token)
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"supervisor thoát sớm: {stderr[-2000:]}")
    raise RuntimeError("supervisor không khởi động trong thời gian cho phép")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except Exception as error:
            last_error = error
        time.sleep(0.25)
    raise RuntimeError(f"endpoint {url} không sẵn sàng: {last_error}")


def new_idempotency_key() -> str:
    return uuid4().hex
