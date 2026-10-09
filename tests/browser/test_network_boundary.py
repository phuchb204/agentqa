from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from agentqa.contracts.actions import Operation
from agentqa.contracts.identity import LocatorAlternative, LocatorKind, TargetDescriptor
from agentqa.contracts.values import LiteralValue
from agentqa.platform.fixtures import FixtureRegistry, synthetic_password
from agentqa.platform.security.egress import AllowedEndpoint
from tests.support.browser import TcpRecorder, TrapServer, run_async, start_stack
from tests.support.browser import action_command as command
from tests.support.taskboard import TaskboardServer


def endpoint(port: int, host: str = "127.0.0.1", addresses: tuple[str, ...] = ("127.0.0.1",)) -> AllowedEndpoint:
    return AllowedEndpoint(host=host, port=port, addresses=addresses)


def taskboard_endpoint(server: TaskboardServer) -> AllowedEndpoint:
    parts = urlsplit(server.base_url)
    return endpoint(parts.port or 80)


def test_allowed_local_fixture_loads(tmp_path: Path) -> None:
    trap = TrapServer()
    trap.route("/hello", body="hello-trap")
    trap.start()
    try:

        async def scenario() -> None:
            stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint(trap.port)])
            try:
                await stack.session.contexts.open("net-allow")
                page = await stack.session.contexts.page("net-allow")
                await page.goto(f"{trap.base_url}/hello")
                assert "hello-trap" in await page.content()
                assert stack.policy.decisions[-1].allowed is True
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        trap.stop()


def test_forbidden_endpoint_fetch_is_blocked(tmp_path: Path) -> None:
    allowed = TrapServer()
    forbidden = TrapServer()
    forbidden.route("/secret", body="secret-trap")
    allowed.start()
    forbidden.start()
    allowed.route(
        "/fetch-page",
        body=(
            "<html><body><script>"
            f'fetch("http://127.0.0.1:{forbidden.port}/secret")'
            ".then(r => { window.__r = r.status; })"
            '.catch(() => { window.__r = "error"; });'
            "</script></body></html>"
        ),
    )
    try:

        async def scenario() -> None:
            stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint(allowed.port)])
            try:
                await stack.session.contexts.open("net-fetch")
                page = await stack.session.contexts.page("net-fetch")
                await page.goto(f"{allowed.base_url}/fetch-page")
                await page.wait_for_function("() => window.__r !== undefined", timeout=15000)
                result = await page.evaluate("() => window.__r")
                assert result != 200
                assert forbidden.requests == []
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        allowed.stop()
        forbidden.stop()


def test_dns_change_is_blocked(tmp_path: Path) -> None:
    allowed = TrapServer()
    forbidden = TrapServer()
    allowed.start()
    forbidden.start()
    allowed.route(
        "/dns-page",
        body=(
            "<html><body><script>"
            f'fetch("http://changing.test:{forbidden.port}/secret")'
            ".then(r => { window.__r = r.status; })"
            '.catch(() => { window.__r = "error"; });'
            "</script></body></html>"
        ),
    )

    def resolver(host: str) -> list[str]:
        if host == "changing.test":
            return ["10.9.9.9"]
        raise OSError(f"resolver không được phép: {host}")

    try:

        async def scenario() -> None:
            stack = await start_stack(
                temp_root=tmp_path,
                endpoints=[endpoint(allowed.port), endpoint(forbidden.port, host="changing.test")],
                resolver=resolver,
            )
            try:
                await stack.session.contexts.open("net-dns")
                page = await stack.session.contexts.page("net-dns")
                await page.goto(f"{allowed.base_url}/dns-page")
                await page.wait_for_function("() => window.__r !== undefined", timeout=15000)
                result = await page.evaluate("() => window.__r")
                assert result != 200
                assert forbidden.requests == []
                assert any("10.9.9.9" in decision.reason for decision in stack.policy.decisions)
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        allowed.stop()
        forbidden.stop()


def test_redirect_to_forbidden_is_blocked(tmp_path: Path) -> None:
    allowed = TrapServer()
    forbidden = TrapServer()
    forbidden.route("/secret", body="secret-trap")
    allowed.start()
    forbidden.start()
    allowed.route(
        "/redir",
        status=302,
        body="",
        headers={"Location": f"http://127.0.0.1:{forbidden.port}/secret"},
    )
    try:

        async def scenario() -> None:
            stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint(allowed.port)])
            try:
                await stack.session.contexts.open("net-redirect")
                page = await stack.session.contexts.page("net-redirect")
                response = await page.goto(f"{allowed.base_url}/redir")
                assert response is not None
                assert response.status == 403
                assert forbidden.requests == []
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        allowed.stop()
        forbidden.stop()


def test_service_worker_fetch_cannot_bypass(tmp_path: Path) -> None:
    allowed = TrapServer()
    forbidden = TrapServer()
    forbidden.route("/secret", body="secret-trap")
    allowed.start()
    forbidden.start()
    allowed.route(
        "/sw-page",
        body=(
            "<html><body><script>"
            'window.__sw = "pending";'
            'navigator.serviceWorker.register("/sw.js")'
            '.catch(() => { window.__sw = "failed"; });'
            'navigator.serviceWorker.ready.then(() => { window.__sw = "ready"; });'
            'setTimeout(() => { if (window.__sw === "pending") { window.__sw = "not-ready"; } }, 2000);'
            "</script></body></html>"
        ),
    )
    allowed.route(
        "/sw.js",
        content_type="application/javascript",
        body=(
            "self.addEventListener('install', (event) => {"
            f'  event.waitUntil(fetch("http://127.0.0.1:{forbidden.port}/secret")'
            '.then((r) => { if (!r.ok) { throw new Error("blocked"); } }));'
            "});"
        ),
    )
    try:

        async def scenario() -> None:
            stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint(allowed.port)])
            try:
                await stack.session.contexts.open("net-sw")
                page = await stack.session.contexts.page("net-sw")
                await page.goto(f"{allowed.base_url}/sw-page")
                await page.wait_for_function("() => window.__sw !== 'pending'", timeout=15000)
                state = await page.evaluate("() => window.__sw")
                assert state in ("failed", "not-ready")
                assert forbidden.requests == []
                denied = [
                    decision
                    for decision in stack.policy.decisions
                    if str(forbidden.port) in decision.target and not decision.allowed
                ]
                assert denied
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        allowed.stop()
        forbidden.stop()


def test_websocket_target_is_blocked(tmp_path: Path) -> None:
    allowed = TrapServer()
    recorder = TcpRecorder()
    allowed.start()
    recorder.start()
    allowed.route(
        "/ws-page",
        body=(
            "<html><body><script>"
            f'const ws = new WebSocket("ws://127.0.0.1:{recorder.port}/");'
            'ws.onopen = () => { window.__ws = "open"; };'
            'ws.onerror = () => { window.__ws = "error"; };'
            "</script></body></html>"
        ),
    )
    try:

        async def scenario() -> None:
            stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint(allowed.port)])
            try:
                await stack.session.contexts.open("net-ws")
                page = await stack.session.contexts.page("net-ws")
                await page.goto(f"{allowed.base_url}/ws-page")
                await page.wait_for_function("() => window.__ws !== undefined", timeout=15000)
                assert await page.evaluate("() => window.__ws") == "error"
                assert recorder.connections == 0
            finally:
                await stack.aclose()

        run_async(scenario())
    finally:
        allowed.stop()
        recorder.stop()


def test_file_access_is_denied(tmp_path: Path, taskboard_server: TaskboardServer) -> None:
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            page = await stack.session.contexts.page(str(run_id))
            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.NAVIGATE,
                    value=LiteralValue(kind="literal", value="file:///D:/WORK/AgentQA/.env"),
                )
            )
            assert receipt.outcome.value == "rejected"
            assert "egress_denied" in receipt.evidence_refs
            content = await page.content()
            assert "AGENTQA_" not in content
        finally:
            await stack.aclose()

    run_async(scenario())


def test_context_and_backend_isolation_via_actions(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    assert fixture_registry.prepare("taskboard@1", "net-iso-a").ok
    assert fixture_registry.prepare("taskboard@1", "net-iso-b").ok
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            login_url = f"{taskboard_server.base_url}/net-iso-a/login"
            await stack.action_port.dispatch(
                command(run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=login_url))
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="username", role="textbox", name="Tài khoản"),
                    value=LiteralValue(kind="literal", value="alice"),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(
                        intent="password",
                        locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")],
                    ),
                    value=LiteralValue(kind="literal", value=synthetic_password("net-iso-a", "alice")),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.CLICK,
                    target=TargetDescriptor(intent="login", role="button", name="Đăng nhập"),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="new_item", role="textbox", name="Việc mới"),
                    value=LiteralValue(kind="literal", value="Việc của A"),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.CLICK,
                    target=TargetDescriptor(intent="create", role="button", name="Thêm việc"),
                )
            )

            await stack.session.contexts.open("context-b")
            page = await stack.session.contexts.page("context-b")
            await page.goto(f"{taskboard_server.base_url}/net-iso-b/tasks")
            assert page.url.endswith("/net-iso-b/login")

            probe_a = fixture_registry.probe("taskboard@1", "net-iso-a")
            probe_b = fixture_registry.probe("taskboard@1", "net-iso-b")
            assert probe_a["label_counts"]["Việc của A"] == 1
            assert probe_b["item_count"] == 0
            assert probe_b["counters"].get("item_created", 0) == 0
        finally:
            await stack.aclose()

    run_async(scenario())
