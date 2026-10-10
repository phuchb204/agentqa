from __future__ import annotations

import asyncio
import contextlib
import socketserver
import sys
import threading
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

from playwright.async_api import Page, async_playwright

from agentqa.agent.browser import (
    BrowserSession,
    PlaywrightActionPort,
    PlaywrightReadPort,
    SafeEvidenceService,
)
from agentqa.agent.browser.journals import DownloadJournal, NetworkJournal
from agentqa.contracts.actions import ActionCommand, Operation
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue, SecretValue, SensitiveValue
from agentqa.platform.security.egress import AllowedEndpoint, EgressPolicy, Resolver
from agentqa.platform.security.proxy import EgressProxy
from agentqa.platform.security.redaction import RedactionService
from agentqa.platform.security.sandbox import select_profile
from agentqa.platform.security.taint import TaintRegistry

T = TypeVar("T")

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def no_dns_resolver(host: str) -> list[str]:
    raise OSError(f"resolver không được phép trong test: {host}")


@asynccontextmanager
async def chromium_page() -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


def action_command(
    run_id: UUID,
    operation: Operation,
    *,
    target: TargetDescriptor | None = None,
    value: LiteralValue | SecretValue | None = None,
    observation_version: int = 1,
    grant_refs: list[str] | None = None,
    page_key: str = "main",
) -> ActionCommand:
    return ActionCommand(
        command_id=uuid4(),
        run_id=run_id,
        attempt_id=uuid4(),
        fence_epoch=1,
        expected_observation_version=observation_version,
        operation=operation,
        target=target,
        value=value,
        page_key=page_key,
        secret_grant_refs=list(grant_refs or []),
    )


class TrapServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self._routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def route(
        self,
        path: str,
        *,
        status: int = 200,
        body: str = "",
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        merged = {"Content-Type": content_type}
        merged.update(headers or {})
        self._routes[path] = (status, merged, body.encode("utf-8"))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> TrapServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append(("GET", self.path))
                status, headers, body = outer._routes.get(self.path, (404, {}, b"not-found"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                self.rfile.read(length)
                outer.requests.append(("POST", self.path))
                status, headers, body = outer._routes.get(self.path, (404, {}, b"not-found"))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None

    def __enter__(self) -> TrapServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


class TcpRecorder:
    def __init__(self) -> None:
        self.connections = 0
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> TcpRecorder:
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                outer.connections += 1
                with contextlib.suppress(OSError):
                    self.request.recv(1024)

        server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None

    def __enter__(self) -> TcpRecorder:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


@dataclass
class RecordingSink:
    records: list[dict[str, Any]] = field(default_factory=list)

    def put(self, label: str, payload: bytes, media_type: str) -> str:
        self.records.append({"label": label, "payload": payload, "media_type": media_type})
        return f"mem://{label}/{len(self.records)}"

    def payloads(self) -> list[bytes]:
        return [record["payload"] for record in self.records]


@dataclass
class FakeSecretBroker:
    secret: str
    calls: list[str] = field(default_factory=list)

    def resolve(self, grant_ref: str) -> SensitiveValue:
        self.calls.append(grant_ref)
        return SensitiveValue(self.secret)


@dataclass
class BrowserStack:
    policy: EgressPolicy
    proxy: EgressProxy
    session: BrowserSession
    evidence: SafeEvidenceService
    read_port: PlaywrightReadPort
    action_port: PlaywrightActionPort
    sink: RecordingSink
    taint: TaintRegistry

    async def aclose(self) -> None:
        await self.session.close()
        await self.proxy.stop()


async def start_stack(
    *,
    temp_root: str | Path,
    endpoints: list[AllowedEndpoint],
    resolver: Resolver = no_dns_resolver,
    secret_broker: Any | None = None,
    file_resolver: Any | None = None,
) -> BrowserStack:
    policy = EgressPolicy(endpoints, resolver=resolver)
    proxy = EgressProxy(policy)
    await proxy.start()
    profile = select_profile(
        workspace_root=str(REPO_ROOT),
        temp_root=str(temp_root),
        proxy_url=proxy.url,
    )
    session = BrowserSession(profile.launch)
    await session.start()
    taint = TaintRegistry()
    sink = RecordingSink()
    evidence = SafeEvidenceService(redactor=RedactionService(taint), sink=sink, taint=taint)
    downloads = DownloadJournal()
    network = NetworkJournal()
    read_port = PlaywrightReadPort(session.contexts, evidence, network=network, downloads=downloads)
    action_port = PlaywrightActionPort(
        session.contexts,
        evidence,
        secret_resolver=secret_broker,
        navigation_guard=policy,
        file_resolver=file_resolver,
        downloads=downloads,
    )
    return BrowserStack(
        policy=policy,
        proxy=proxy,
        session=session,
        evidence=evidence,
        read_port=read_port,
        action_port=action_port,
        sink=sink,
        taint=taint,
    )
