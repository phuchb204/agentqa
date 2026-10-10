from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.security.origin import OriginPolicy
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage.roles import ROLE_API

pytestmark = pytest.mark.asyncio


async def test_shared_profile_rejects_insecure_configuration() -> None:
    with pytest.raises(SecurityError):
        OriginPolicy.shared([])
    with pytest.raises(SecurityError):
        OriginPolicy.shared(["http://qa.example.com"])
    with pytest.raises(SecurityError):
        OriginPolicy.shared(["https://127.0.0.1:8443"])
    policy = OriginPolicy.shared(["https://qa.example.com"])
    assert policy.profile == "shared"
    assert policy.secure_cookies is True
    assert OriginPolicy.local().secure_cookies is False


async def test_shared_bootstrap_is_forbidden(test_db) -> None:
    shared_origin = "https://qa.example.com"
    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.shared(frozenset({shared_origin})),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)},
    )
    try:
        await runtime.users.create(username=f"owner-{uuid4().hex[:8]}", password="pw-123456")
        with pytest.raises(SecurityError):
            runtime.bootstrap.issue_nonce()
        app = create_application(runtime)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=shared_origin, headers={"Origin": shared_origin}
        ) as client:
            response = await client.post("/api/v1/auth/local-bootstrap", json={"nonce": "x"})
        assert response.status_code == 403
    finally:
        await runtime.aclose()


async def test_local_bootstrap_requires_loopback_client(runtime) -> None:
    _owner_id, username = None, None
    from tests.support.security import create_user

    _owner_id, username = await create_user(runtime, "owner", "pw-123456")
    ticket = runtime.bootstrap.issue_nonce()
    with pytest.raises(SecurityError):
        await runtime.bootstrap.exchange(
            nonce=ticket.nonce,
            origin="http://127.0.0.1:8000",
            request_host="127.0.0.1:8000",
            client_host="10.10.0.5",
            owner_user_id=_owner_id,
            owner_username=username,
        )
    result = await runtime.bootstrap.exchange(
        nonce=ticket.nonce,
        origin="http://127.0.0.1:8000",
        request_host="127.0.0.1:8000",
        client_host="127.0.0.1",
        owner_user_id=_owner_id,
        owner_username=username,
    )
    assert result.session_id is not None
    with pytest.raises(SecurityError):
        await runtime.bootstrap.exchange(
            nonce=ticket.nonce,
            origin="http://127.0.0.1:8000",
            request_host="127.0.0.1:8000",
            client_host="127.0.0.1",
            owner_user_id=_owner_id,
            owner_username=username,
        )


async def test_shared_origin_allowlist_blocks_other_origins(test_db) -> None:
    shared_origin = "https://qa.example.com"
    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.shared(frozenset({shared_origin})),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)},
    )
    username = f"erin-{uuid4().hex[:8]}"
    try:
        await runtime.users.create(username=username, password="pw-123456")
        app = create_application(runtime)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url=shared_origin,
            headers={"Origin": "https://evil.example.com"},
        ) as client:
            response = await client.post("/api/v1/auth/login", json={"username": username, "password": "pw-123456"})
        assert response.status_code == 403
    finally:
        await runtime.aclose()


async def test_local_session_cookie_not_secure_and_shared_is_secure(runtime, api_client) -> None:
    from tests.support.security import create_user

    _user_id, username = await create_user(runtime, "cookie", "pw-123456")
    response = await api_client.post("/api/v1/auth/login", json={"username": username, "password": "pw-123456"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Secure" not in cookie
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()
