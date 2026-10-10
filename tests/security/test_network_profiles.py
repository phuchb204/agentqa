from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentqa.agent.browser.contexts import PROVIDER_ENV_VARS, BrowserLaunchConfig, SandboxUnsupported
from agentqa.platform.security.egress import AllowedEndpoint, EgressDenied, EgressPolicy
from agentqa.platform.security.proxy import EgressProxy

pytestmark = pytest.mark.asyncio

ALLOWED_ADDRESS = "93.184.216.34"


def _policy(resolver) -> EgressPolicy:
    return EgressPolicy(
        [
            AllowedEndpoint(host="app.test", port=443, addresses=(ALLOWED_ADDRESS,)),
            AllowedEndpoint(host="app.test", port=80, addresses=(ALLOWED_ADDRESS,)),
        ],
        resolver=resolver,
    )


async def test_dns_rebinding_resolved_address_must_match_allowlist() -> None:
    policy = _policy(lambda host: ["10.0.0.5"])
    with pytest.raises(EgressDenied):
        policy.check_url("https://app.test/")
    assert any("resolve" in decision.reason for decision in policy.decisions if not decision.allowed)


async def test_redirect_and_control_plane_destinations_denied() -> None:
    policy = _policy(lambda host: [ALLOWED_ADDRESS])
    assert policy.check_url("https://app.test/login")
    with pytest.raises(EgressDenied):
        policy.check_redirect("https://evil.test/steal")
    with pytest.raises(EgressDenied):
        policy.check_url("http://127.0.0.1:8000/api/v1/workspaces")
    with pytest.raises(EgressDenied):
        policy.check_url("http://169.254.169.254/latest/meta-data")


async def test_file_and_websocket_schemes_are_checked() -> None:
    policy = _policy(lambda host: [ALLOWED_ADDRESS])
    with pytest.raises(EgressDenied):
        policy.check_url("file:///etc/passwd")
    with pytest.raises(EgressDenied):
        policy.check_url("ftp://app.test/file")
    assert policy.check_url("ws://app.test/socket")
    assert policy.check_url("wss://app.test/socket")
    with pytest.raises(EgressDenied):
        policy.check_url("ws://app.test:81/socket")
    with pytest.raises(EgressDenied):
        policy.check_url("wss://other.test/socket")


async def test_proxy_enforces_allowlist_for_all_channels() -> None:
    async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = server.sockets[0].getsockname()[1]
    proxy = EgressProxy(EgressPolicy([AllowedEndpoint(host="127.0.0.1", port=upstream_port, addresses=("127.0.0.1",))]))
    await proxy.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(
            f"GET http://127.0.0.1:{upstream_port}/health HTTP/1.1\r\nHost: 127.0.0.1:{upstream_port}\r\n\r\n".encode()
        )
        await writer.drain()
        response = (await reader.read()).decode("latin-1")
        writer.close()
        assert "200 OK" in response

        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"GET http://127.0.0.1:1/secret HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        await writer.drain()
        denied = (await reader.read()).decode("latin-1")
        writer.close()
        assert "403 Forbidden" in denied

        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT evil.test:443 HTTP/1.1\r\nHost: evil.test:443\r\n\r\n")
        await writer.drain()
        denied_tunnel = (await reader.read()).decode("latin-1")
        writer.close()
        assert "403 Forbidden" in denied_tunnel
        assert any(request.startswith("CONNECT evil.test:443") for request in proxy.requests)
    finally:
        await proxy.stop()
        server.close()
        await server.wait_closed()


async def test_windows_profile_requires_proxy_and_isolated_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    from agentqa.platform.security.sandbox_windows import windows_profile

    profile = windows_profile(workspace_root=str(workspace), temp_root=str(sandbox), proxy_url="http://127.0.0.1:9")
    assert profile.platform == "win32"
    assert profile.launch.proxy_url == "http://127.0.0.1:9"

    with pytest.raises(SandboxUnsupported) as missing_proxy:
        windows_profile(workspace_root=str(workspace), temp_root=str(sandbox), proxy_url="")
    assert any("proxy_url" in reason for reason in missing_proxy.value.reasons)

    with pytest.raises(SandboxUnsupported) as inside_workspace:
        BrowserLaunchConfig(
            proxy_url="http://127.0.0.1:9",
            user_data_dir=str(workspace / "profile"),
            download_dir=str(sandbox / "downloads"),
            workspace_root=str(workspace),
            temp_root=str(sandbox),
        ).enforce()
    assert any("nằm trong workspace" in reason for reason in inside_workspace.value.reasons)

    with pytest.raises(SandboxUnsupported) as outside_temp:
        BrowserLaunchConfig(
            proxy_url="http://127.0.0.1:9",
            user_data_dir=str(sandbox / "profile"),
            download_dir=str(tmp_path / "elsewhere" / "downloads"),
            workspace_root=str(workspace),
            temp_root=str(sandbox),
        ).enforce()
    assert any("temp root" in reason for reason in outside_temp.value.reasons)


async def test_clean_environment_scrubs_provider_and_control_vars(tmp_path: Path) -> None:
    launch = BrowserLaunchConfig(
        proxy_url="http://127.0.0.1:9",
        user_data_dir=str(tmp_path / "profile"),
        download_dir=str(tmp_path / "downloads"),
        workspace_root=str(tmp_path / "workspace"),
        temp_root=str(tmp_path),
        env_overrides={"TEMP": str(tmp_path)},
    )
    base = {"SAFE_VALUE": "1"}
    for name in PROVIDER_ENV_VARS:
        base[name] = "secret"
    base["AGENTQA_CUSTOM_API_KEY"] = "secret"
    environment = launch.clean_environment(base)
    assert "SAFE_VALUE" in environment
    assert environment["TEMP"] == str(tmp_path)
    for name in PROVIDER_ENV_VARS:
        assert name not in environment
    assert "AGENTQA_CUSTOM_API_KEY" not in environment
