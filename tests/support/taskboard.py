from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn

from agentqa.platform.fixtures import TaskboardFixture, synthetic_password

FIXTURE_DATA_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "browser"


def load_scenario(name: str) -> dict:
    return json.loads((FIXTURE_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class TaskboardServer:
    base_url: str
    control_token: str


@contextmanager
def start_taskboard_server() -> Iterator[TaskboardServer]:
    from taskboard import create_taskboard_app

    control_token = secrets.token_urlsafe(16)
    app = create_taskboard_app(control_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="taskboard-fixture", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Taskboard fixture server không khởi động được")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield TaskboardServer(base_url=f"http://127.0.0.1:{port}", control_token=control_token)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class TaskboardHttp:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url, follow_redirects=True, timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def login(self, namespace: str, username: str, password: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/login", data={"username": username, "password": password})

    def create_item(self, namespace: str, label: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/tasks", data={"action": "create", "label": label})

    def create_async(self, namespace: str, label: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/tasks", data={"action": "async", "label": label})

    def relabel_item(self, namespace: str, item_id: str, label: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/tasks/{item_id}/relabel", data={"label": label})

    def toggle_item(self, namespace: str, item_id: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/tasks/{item_id}/toggle")

    def delete_item(self, namespace: str, item_id: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/tasks/{item_id}/delete")


def alice_session(base_url: str, namespace: str) -> TaskboardHttp:
    http = TaskboardHttp(base_url)
    response = http.login(namespace, "alice", synthetic_password(namespace, "alice"))
    response.raise_for_status()
    return http


def build_registry(server: TaskboardServer):
    from agentqa.platform.fixtures import FixtureRegistry

    registry = FixtureRegistry()
    registry.register(TaskboardFixture(server.base_url, server.control_token))
    return registry
