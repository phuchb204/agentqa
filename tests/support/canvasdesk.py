from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
import uvicorn

from agentqa.platform.fixtures import CanvasdeskFixture, canvasdesk_password


@dataclass(frozen=True)
class CanvasdeskServer:
    base_url: str
    control_token: str


@contextmanager
def start_canvasdesk_server() -> Iterator[CanvasdeskServer]:
    from canvasdesk import create_canvasdesk_app

    control_token = secrets.token_urlsafe(16)
    app = create_canvasdesk_app(control_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="canvasdesk-fixture", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Canvasdesk fixture server không khởi động được")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield CanvasdeskServer(base_url=f"http://127.0.0.1:{port}", control_token=control_token)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class CanvasdeskHttp:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url, follow_redirects=True, timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def login(self, namespace: str, username: str, password: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/login", data={"username": username, "password": password})


def alice_session(base_url: str, namespace: str) -> CanvasdeskHttp:
    http = CanvasdeskHttp(base_url)
    response = http.login(namespace, "alice", canvasdesk_password(namespace, "alice"))
    response.raise_for_status()
    return http


def build_canvasdesk_fixture(server: CanvasdeskServer) -> CanvasdeskFixture:
    return CanvasdeskFixture(server.base_url, server.control_token)
