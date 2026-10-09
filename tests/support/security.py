from __future__ import annotations

from uuid import UUID, uuid4

import httpx

from agentqa.platform.api.error_models import ErrorResponse
from agentqa.platform.api.runtime import PlatformRuntime

ORIGIN = "http://127.0.0.1:8000"


async def create_user(runtime: PlatformRuntime, prefix: str, password: str) -> tuple[UUID, str]:
    username = f"{prefix}-{uuid4().hex[:8]}"
    user = await runtime.users.create(username=username, password=password)
    return user.id, username


async def create_user_by_name(runtime: PlatformRuntime, username: str, password: str) -> UUID:
    user = await runtime.users.create(username=username, password=password)
    return user.id


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token, "Origin": ORIGIN}


def error_body(response: httpx.Response) -> ErrorResponse:
    return ErrorResponse.model_validate(response.json())


async def create_workspace(client: httpx.AsyncClient, csrf_token: str, slug: str) -> str:
    response = await client.post(
        "/api/v1/workspaces",
        json={"slug": slug, "name": slug},
        headers=csrf_headers(csrf_token),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]
