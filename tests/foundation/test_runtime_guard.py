from __future__ import annotations

import http.client
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.support import network_guard


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"fixture-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_provider_egress_denied_even_with_fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTQA_JEV_API_KEY", "canary-fake-key")
    monkeypatch.setenv("AGENTQA_LLM_API_KEY", "canary-fake-key")
    with pytest.raises(network_guard.NetworkGuardError):
        socket.create_connection(("opencode.ai", 443), timeout=1)
    with pytest.raises(network_guard.NetworkGuardError):
        socket.getaddrinfo("api.opencode.ai", 443)


def test_provider_env_stripped_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTQA_JEV_API_KEY", "canary-fake-key")
    removed = network_guard.strip_provider_env()
    assert "AGENTQA_JEV_API_KEY" in removed
    assert "AGENTQA_JEV_API_KEY" not in os.environ
    assert "canary-fake-key" not in os.environ.values()
    monkeypatch.setenv("AGENTQA_LLM_API_KEY", "canary-fake-key")
    assert "AGENTQA_LLM_API_KEY" not in network_guard.sanitized_environment()


def test_declared_local_fixture_endpoint_allowed() -> None:
    server = HTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b"fixture-ok"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()


def test_extra_declared_hosts_are_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTQA_TEST_ALLOWED_HOSTS", "fixture.internal, second.internal")
    allowed = network_guard.declared_allowed_hosts()
    assert "fixture.internal" in allowed
    assert "second.internal" in allowed
    network_guard.guard_host("fixture.internal")


def test_guard_is_installed_for_the_session() -> None:
    assert getattr(socket.socket, network_guard.GUARD_ATTRIBUTE, False) is True
