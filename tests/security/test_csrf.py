from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.storage.roles import ROLE_API
from tests.support.security import create_user, csrf_headers, error_body, login

pytestmark = pytest.mark.asyncio


async def _make_user_and_login(api_client, runtime) -> str:
    _user_id, username = await create_user(runtime, "csrf", "pw-123456")
    return await login(api_client, username, "pw-123456")


async def test_login_requires_origin(api_client, runtime) -> None:
    _user_id, username = await create_user(runtime, "csrf", "pw-123456")
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "pw-123456"},
        headers={"Origin": ""},
    )
    assert response.status_code == 403
    assert error_body(response).code is ErrorCode.PERMISSION_DENIED


async def test_wrong_origin_denied(api_client, runtime) -> None:
    _user_id, username = await create_user(runtime, "csrf", "pw-123456")
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "pw-123456"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403


async def test_same_host_wrong_port_denied(api_client, runtime) -> None:
    _user_id, username = await create_user(runtime, "csrf", "pw-123456")
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "pw-123456"},
        headers={"Origin": "http://127.0.0.1:9999"},
    )
    assert response.status_code == 403


async def test_cookie_mutation_requires_csrf(api_client, runtime) -> None:
    csrf = await _make_user_and_login(api_client, runtime)
    payload = {"slug": f"ws-{uuid4().hex[:8]}", "name": "Workspace"}

    response = await api_client.post("/api/v1/workspaces", json=payload)
    assert response.status_code == 403

    response = await api_client.post(
        "/api/v1/workspaces", json=payload, headers={"X-CSRF-Token": "bogus", "Origin": "http://127.0.0.1:8000"}
    )
    assert response.status_code == 403

    response = await api_client.post("/api/v1/workspaces", json=payload, headers=csrf_headers(csrf))
    assert response.status_code == 200, response.text


async def test_pat_mutation_skips_browser_guard(api_client, runtime) -> None:
    csrf = await _make_user_and_login(api_client, runtime)
    response = await api_client.post("/api/v1/auth/tokens", json={"name": "ci"}, headers=csrf_headers(csrf))
    assert response.status_code == 200, response.text
    token = response.json()["token"]

    transport = httpx.ASGITransport(app=create_application(runtime))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as cli_client:
        response = await cli_client.post(
            "/api/v1/workspaces",
            json={"slug": f"ws-{uuid4().hex[:8]}", "name": "CLI Workspace"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text


async def test_shared_profile_origin_allowlist(test_db) -> None:
    shared_origin = "https://qa.example.com"
    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.shared(frozenset({shared_origin})),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)},
    )
    try:
        await runtime.users.create(username=f"shared-{uuid4().hex[:8]}", password="pw-123456")
        transport = httpx.ASGITransport(app=create_application(runtime))
        async with httpx.AsyncClient(transport=transport, base_url=shared_origin) as client:
            denied = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "pw-123456"},
                headers={"Origin": "https://evil.example"},
            )
            assert denied.status_code == 403
            allowed = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "pw-123456"},
                headers={"Origin": shared_origin},
            )
            assert allowed.status_code == 401
    finally:
        await runtime.aclose()
