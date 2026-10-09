from __future__ import annotations

import json
import pickle
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import SensitiveValue
from agentqa.platform.identity.models import IdentityError
from agentqa.platform.identity.sessions import SessionService
from agentqa.platform.identity.tokens import hash_token
from agentqa.platform.identity.users import UserService
from agentqa.platform.storage.database import create_engine
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import fetch_all
from tests.support.security import create_user, login

pytestmark = pytest.mark.asyncio


async def test_login_rejects_wrong_password(runtime) -> None:
    _user_id, username = await create_user(runtime, "alice", "correct-horse")
    with pytest.raises(IdentityError) as error:
        await runtime.sessions.login(username=username, password="wrong")
    assert error.value.code is ErrorCode.PROVIDER_AUTH


async def test_session_token_is_opaque_and_stored_hashed(runtime, test_db) -> None:
    _user_id, username = await create_user(runtime, "alice", "correct-horse")
    result = await runtime.sessions.login(username=username, password="correct-horse")
    rows = await fetch_all(
        test_db.dsn(ROLE_API),
        "SELECT token_hash, csrf_hash FROM sessions WHERE id = :id",
        {"id": result.session_id},
    )
    stored_token_hash, stored_csrf_hash = rows[0]
    assert stored_token_hash == hash_token(result.raw_token)
    assert result.raw_token != stored_token_hash
    assert stored_csrf_hash == hash_token(result.csrf_token)
    assert len(result.raw_token) >= 32
    principal = await runtime.sessions.authenticate(result.raw_token)
    assert principal.user_id == result.user_id
    assert principal.session_id == result.session_id
    assert principal.csrf_hash == stored_csrf_hash


async def test_logout_revokes_session(runtime) -> None:
    _user_id, username = await create_user(runtime, "alice", "correct-horse")
    result = await runtime.sessions.login(username=username, password="correct-horse")
    await runtime.sessions.logout(result.raw_token)
    with pytest.raises(IdentityError):
        await runtime.sessions.authenticate(result.raw_token)


async def test_rotate_invalidates_old_session(runtime) -> None:
    _user_id, username = await create_user(runtime, "alice", "correct-horse")
    result = await runtime.sessions.login(username=username, password="correct-horse")
    rotated = await runtime.sessions.rotate(result.raw_token)
    assert rotated.raw_token != result.raw_token
    with pytest.raises(IdentityError):
        await runtime.sessions.authenticate(result.raw_token)
    principal = await runtime.sessions.authenticate(rotated.raw_token)
    assert principal.user_id == result.user_id


async def test_expired_session_rejected(test_db) -> None:
    engine: AsyncEngine = create_engine(test_db.dsn(ROLE_API))
    try:
        users = UserService(engine)
        username = f"expired-{uuid4().hex[:8]}"
        user = await users.create(username=username, password="pw-123456")
        sessions = SessionService(engine, ttl=timedelta(seconds=-5))
        result = await sessions.login(username=username, password="pw-123456")
        with pytest.raises(IdentityError):
            await sessions.authenticate(result.raw_token)
        assert user.id == result.user_id
    finally:
        await engine.dispose()


async def test_pat_issued_once_and_hash_only(runtime, test_db) -> None:
    user_id, _username = await create_user(runtime, "bob", "pw-123456")
    issued = await runtime.tokens.create(user_id=user_id, name="ci", scopes=("run.submit",))
    principal = await runtime.tokens.authenticate(issued.raw_token)
    assert principal.token_id == issued.record.id
    assert principal.scopes == ("run.submit",)
    rows = await fetch_all(
        test_db.dsn(ROLE_API),
        "SELECT token_hash, scopes FROM api_tokens WHERE id = :id",
        {"id": issued.record.id},
    )
    assert rows[0][0] == hash_token(issued.raw_token)
    assert issued.raw_token not in str(rows[0][0])
    with pytest.raises(IdentityError):
        await runtime.tokens.authenticate("not-a-real-token")


async def test_pat_expiry_and_revocation(runtime) -> None:
    user_id, _username = await create_user(runtime, "carol", "pw-123456")
    expired = await runtime.tokens.create(
        user_id=user_id,
        name="expired",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    with pytest.raises(IdentityError):
        await runtime.tokens.authenticate(expired.raw_token)

    active = await runtime.tokens.create(user_id=user_id, name="active")
    await runtime.tokens.revoke(token_id=active.record.id, user_id=user_id, reason="done")
    with pytest.raises(IdentityError):
        await runtime.tokens.authenticate(active.raw_token)
    records = await runtime.tokens.list_for_user(user_id)
    assert all(active.raw_token not in repr(record) for record in records)


async def test_api_login_cookie_flags_local(api_client, runtime) -> None:
    _user_id, username = await create_user(runtime, "dave", "pw-123456")
    response = await api_client.post("/api/v1/auth/login", json={"username": username, "password": "pw-123456"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower()
    assert "Secure" not in cookie
    assert response.json()["csrf_token"]


async def test_api_shared_profile_cookie_is_secure(test_db) -> None:
    import httpx

    from agentqa.platform.api.application import create_application
    from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile

    shared_origin = "https://qa.example.com"
    profile = RuntimeProfile.shared(frozenset({shared_origin}))
    runtime = PlatformRuntime.build(profile=profile, dsn_by_role={ROLE_API: test_db.dsn(ROLE_API)})
    username = f"erin-{uuid4().hex[:8]}"
    try:
        await runtime.users.create(username=username, password="pw-123456")
        app = create_application(runtime)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=shared_origin, headers={"Origin": shared_origin}
        ) as client:
            response = await client.post("/api/v1/auth/login", json={"username": username, "password": "pw-123456"})
        assert response.status_code == 200, response.text
        assert "Secure" in response.headers["set-cookie"]
    finally:
        await runtime.aclose()


async def test_api_session_endpoint(api_client, runtime) -> None:
    _user_id, username = await create_user(runtime, "frank", "pw-123456")
    csrf = await login(api_client, username, "pw-123456")
    assert csrf
    response = await api_client.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json()["username"] == username


async def test_sensitive_value_not_serializable() -> None:
    value = SensitiveValue("super-secret-canary")
    with pytest.raises(TypeError):
        json.dumps(value)
    assert "super-secret-canary" not in repr(value)
    with pytest.raises(TypeError):
        pickle.dumps(value)
