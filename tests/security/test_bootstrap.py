from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.identity.bootstrap import LocalBootstrapService
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage.roles import ROLE_API
from tests.support.security import ORIGIN, create_user

pytestmark = pytest.mark.asyncio


async def test_local_bootstrap_nonce_is_single_use(api_client, runtime) -> None:
    _user_id, _username = await create_user(runtime, "owner", "pw-123456")
    ticket = runtime.bootstrap.issue_nonce()
    response = await api_client.post("/api/v1/auth/local-bootstrap", json={"nonce": ticket.nonce})
    assert response.status_code == 200, response.text
    assert response.json()["csrf_token"]
    replay = await api_client.post("/api/v1/auth/local-bootstrap", json={"nonce": ticket.nonce})
    assert replay.status_code == 403


async def test_bootstrap_nonce_not_in_logs_or_response(api_client, runtime, caplog) -> None:
    await create_user(runtime, "owner", "pw-123456")
    ticket = runtime.bootstrap.issue_nonce()
    with caplog.at_level(logging.DEBUG):
        response = await api_client.post("/api/v1/auth/local-bootstrap", json={"nonce": ticket.nonce})
    assert response.status_code == 200
    assert ticket.nonce not in response.text
    assert ticket.nonce not in caplog.text


async def test_bootstrap_rejects_non_loopback_client(runtime) -> None:
    owner_id, owner_name = await create_user(runtime, "owner", "pw-123456")
    ticket = runtime.bootstrap.issue_nonce()
    with pytest.raises(SecurityError) as error:
        await runtime.bootstrap.exchange(
            nonce=ticket.nonce,
            origin=ORIGIN,
            request_host="127.0.0.1:8000",
            client_host="203.0.113.7",
            owner_user_id=owner_id,
            owner_username=owner_name,
        )
    assert ticket.nonce not in str(error.value)


async def test_bootstrap_rejects_non_loopback_client_via_api(test_db) -> None:
    runtime = PlatformRuntime.build(profile=RuntimeProfile.local(), dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)})
    try:
        await create_user(runtime, "owner", "pw-123456")
        ticket = runtime.bootstrap.issue_nonce()
        app = create_application(runtime)
        transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 45000))
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            response = await client.post("/api/v1/auth/local-bootstrap", json={"nonce": ticket.nonce})
        assert response.status_code == 403
    finally:
        await runtime.aclose()


async def test_bootstrap_expired_nonce_rejected(role_engines, runtime) -> None:
    owner_id, owner_name = await create_user(runtime, "owner", "pw-123456")
    short_lived = LocalBootstrapService(
        policy=runtime.profile.origin_policy(), sessions=runtime.sessions, ttl=timedelta(seconds=-1)
    )
    ticket = short_lived.issue_nonce()
    with pytest.raises(IdentityError):
        await short_lived.exchange(
            nonce=ticket.nonce,
            origin=ORIGIN,
            request_host="127.0.0.1:8000",
            client_host="127.0.0.1",
            owner_user_id=owner_id,
            owner_username=owner_name,
        )


async def test_shared_profile_forbids_bootstrap(test_db) -> None:
    shared_origin = "https://qa.example.com"
    runtime = PlatformRuntime.build(
        profile=RuntimeProfile.shared(frozenset({shared_origin})),
        dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)},
    )
    try:
        with pytest.raises(SecurityError):
            runtime.bootstrap.issue_nonce()
        await runtime.users.create(username=f"owner-{uuid4().hex[:8]}", password="pw-123456")
        transport = httpx.ASGITransport(app=create_application(runtime))
        async with httpx.AsyncClient(transport=transport, base_url=shared_origin) as client:
            response = await client.post(
                "/api/v1/auth/local-bootstrap",
                json={"nonce": "whatever"},
                headers={"Origin": shared_origin},
            )
        assert response.status_code == 403
    finally:
        await runtime.aclose()


async def test_bootstrap_nonce_is_not_a_query_parameter(api_client) -> None:
    response = await api_client.get("/api/v1/auth/local-bootstrap")
    assert response.status_code == 405
