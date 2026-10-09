from __future__ import annotations

import asyncio

import pytest

from agentqa.platform.security.egress import AllowedEndpoint, EgressDenied, EgressPolicy
from agentqa.platform.security.proxy import EgressProxy
from tests.support.browser import TrapServer, no_dns_resolver


def local_endpoint(port: int, host: str = "127.0.0.1") -> AllowedEndpoint:
    return AllowedEndpoint(host=host, port=port, addresses=("127.0.0.1",))


async def proxy_exchange(proxy: EgressProxy, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
    writer.write(request)
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data


def status_of(response: bytes) -> int:
    first = response.split(b"\r\n", 1)[0].split(b" ")
    return int(first[1]) if len(first) > 1 else 0


def test_policy_allows_matching_endpoint() -> None:
    policy = EgressPolicy([local_endpoint(1234)], resolver=no_dns_resolver)
    endpoint = policy.check_url("http://127.0.0.1:1234/ok")
    assert endpoint.port == 1234
    assert policy.decisions[-1].allowed is True


@pytest.mark.parametrize(
    "target",
    [
        "file:///D:/WORK/AgentQA/.env",
        "http://127.0.0.1:4321/nope",
        "https://127.0.0.1:4321/nope",
        "http://evil.test:1234/nope",
    ],
)
def test_policy_denies_forbidden_targets(target: str) -> None:
    policy = EgressPolicy([local_endpoint(1234)], resolver=no_dns_resolver)
    with pytest.raises(EgressDenied):
        policy.check_url(target)
    assert policy.decisions[-1].allowed is False


def test_policy_denies_dns_change() -> None:
    policy = EgressPolicy(
        [AllowedEndpoint(host="changing.test", port=8080, addresses=("127.0.0.1",))],
        resolver=lambda host: ["10.1.2.3"],
    )
    with pytest.raises(EgressDenied):
        policy.check_url("http://changing.test:8080/secret")
    assert "10.1.2.3" in policy.decisions[-1].reason


def test_policy_rechecks_redirect_targets() -> None:
    policy = EgressPolicy([local_endpoint(1234)], resolver=no_dns_resolver)
    policy.check_url("http://127.0.0.1:1234/start")
    with pytest.raises(EgressDenied):
        policy.check_redirect("http://127.0.0.1:4321/after-redirect")


@pytest.mark.asyncio
async def test_proxy_forwards_allowed_and_denies_forbidden() -> None:
    allowed = TrapServer()
    forbidden = TrapServer()
    allowed.route("/hello", body="hello-trap")
    forbidden.route("/secret", body="secret-trap")
    allowed.start()
    forbidden.start()
    proxy = EgressProxy(EgressPolicy([local_endpoint(allowed.port)], resolver=no_dns_resolver))
    await proxy.start()
    try:
        allowed_request = (
            f"GET http://127.0.0.1:{allowed.port}/hello HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        response = await proxy_exchange(proxy, allowed_request.encode())
        assert status_of(response) == 200
        assert b"hello-trap" in response
        assert ("GET", "/hello") in allowed.requests

        denied = await proxy_exchange(
            proxy,
            (
                f"GET http://127.0.0.1:{forbidden.port}/secret HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            ).encode(),
        )
        assert status_of(denied) == 403
        assert forbidden.requests == []
    finally:
        await proxy.stop()
        allowed.stop()
        forbidden.stop()


@pytest.mark.asyncio
async def test_proxy_connect_tunnel_and_forbidden_connect() -> None:
    allowed = TrapServer()
    allowed.route("/inside", body="tunnel-ok")
    allowed.start()
    proxy = EgressProxy(EgressPolicy([local_endpoint(allowed.port)], resolver=no_dns_resolver))
    await proxy.start()
    try:
        reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
        writer.write(f"CONNECT 127.0.0.1:{allowed.port} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
        await writer.drain()
        established = await reader.readuntil(b"\r\n\r\n")
        assert b"200 Connection Established" in established
        writer.write(b"GET /inside HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        payload = await reader.read()
        assert b"tunnel-ok" in payload
        writer.close()

        denied = await proxy_exchange(
            proxy,
            b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        )
        assert status_of(denied) == 403
    finally:
        await proxy.stop()
        allowed.stop()
