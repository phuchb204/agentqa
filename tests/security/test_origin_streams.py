from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentqa.platform.api.streams import browser_stream
from tests.support.security import create_user, create_workspace, csrf_headers, login

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self, runtime, *, origin: str | None, host: str = "127.0.0.1:8000", cookies=None) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        self.headers = {"origin": origin, "host": host}
        self.cookies = cookies or {}
        self.closed: tuple[int, str] | None = None
        self.accepted = False
        self.sent: list[dict] = []

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def _owner_session(api_client, runtime) -> str:
    _user_id, username = await create_user(runtime, "stream", "pw-123456")
    csrf = await login(api_client, username, "pw-123456")
    return csrf


async def test_browser_stream_rejects_bad_origin(runtime) -> None:
    websocket = FakeWebSocket(runtime, origin="https://evil.example.com", cookies={"agentqa_session": "x"})
    await browser_stream(websocket, uuid4(), uuid4())
    assert websocket.closed == (4403, "origin_rejected")
    assert websocket.accepted is False


async def test_browser_stream_requires_session(runtime) -> None:
    websocket = FakeWebSocket(runtime, origin="http://127.0.0.1:8000", cookies={})
    await browser_stream(websocket, uuid4(), uuid4())
    assert websocket.closed == (4401, "unauthenticated")


async def test_browser_stream_rejects_revoked_session(api_client, runtime) -> None:
    from uuid import UUID

    _user_id, username = await create_user(runtime, "revoked", "pw-123456")
    csrf = await login(api_client, username, "pw-123456")
    workspace_id = await create_workspace(api_client, csrf, f"ws-{uuid4().hex[:6]}")
    cookie = api_client.cookies.get("agentqa_session")
    assert cookie is not None
    logout = await api_client.post("/api/v1/auth/logout", headers=csrf_headers(csrf))
    assert logout.status_code == 204, logout.text
    websocket = FakeWebSocket(runtime, origin="http://127.0.0.1:8000", cookies={"agentqa_session": cookie})
    await browser_stream(websocket, UUID(workspace_id), uuid4())
    assert websocket.closed == (4401, "unauthenticated")


async def test_browser_stream_missing_run_closes_4404(api_client, runtime) -> None:
    from uuid import UUID

    csrf = await _owner_session(api_client, runtime)
    workspace_id = await create_workspace(api_client, csrf, f"ws-{uuid4().hex[:6]}")
    cookie = api_client.cookies.get("agentqa_session")
    assert cookie is not None
    websocket = FakeWebSocket(runtime, origin="http://127.0.0.1:8000", cookies={"agentqa_session": cookie})
    await browser_stream(websocket, UUID(workspace_id), uuid4())
    assert websocket.closed == (4404, "run_not_found")


async def test_revoked_pat_blocked_on_event_stream(api_client, runtime) -> None:
    csrf = await _owner_session(api_client, runtime)
    workspace_id = await create_workspace(api_client, csrf, f"ws-{uuid4().hex[:6]}")
    created = await api_client.post(
        "/api/v1/auth/tokens",
        json={"name": "ci", "scopes": ["workspace.read"]},
        headers=csrf_headers(csrf),
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    active = await api_client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:8000"},
    )
    assert active.status_code == 200
    principal = await runtime.tokens.authenticate(token)
    await runtime.tokens.revoke(token_id=principal.token_id, user_id=principal.user_id, reason="test")
    run_id = uuid4()
    after = await api_client.get(
        f"/api/v1/workspaces/{workspace_id}/runs/{run_id}/events/stream?cursor=0",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:8000"},
    )
    assert after.status_code in (401, 403)
    assert "event-stream" not in after.headers.get("content-type", "")
