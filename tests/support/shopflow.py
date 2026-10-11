from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
import uvicorn

from agentqa.platform.fixtures import ShopflowFixture, shopflow_password


@dataclass(frozen=True)
class ShopflowServer:
    base_url: str
    control_token: str


@contextmanager
def start_shopflow_server() -> Iterator[ShopflowServer]:
    from shopflow import create_shopflow_app

    control_token = secrets.token_urlsafe(16)
    app = create_shopflow_app(control_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="shopflow-fixture", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Shopflow fixture server không khởi động được")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield ShopflowServer(base_url=f"http://127.0.0.1:{port}", control_token=control_token)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class ShopflowHttp:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url, follow_redirects=True, timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def login(self, namespace: str, username: str, password: str) -> httpx.Response:
        return self.client.post(f"/{namespace}/login", data={"username": username, "password": password})

    def add_to_cart(self, namespace: str, product_id: str, qty: int = 1) -> httpx.Response:
        return self.client.post(f"/{namespace}/cart/lines", data={"product_id": product_id, "qty": qty})


def alice_session(base_url: str, namespace: str) -> ShopflowHttp:
    http = ShopflowHttp(base_url)
    response = http.login(namespace, "alice", shopflow_password(namespace, "alice"))
    response.raise_for_status()
    return http


def build_shopflow_fixture(server: ShopflowServer) -> ShopflowFixture:
    return ShopflowFixture(server.base_url, server.control_token)
