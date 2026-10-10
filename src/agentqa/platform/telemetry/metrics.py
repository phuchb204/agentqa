from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

REQUEST_ID_HEADER = "x-request-id"
request_identifier: ContextVar[str | None] = ContextVar("agentqa_request_id", default=None)

REQUEST_COUNTERS: dict[str, int] = {
    "requests_total": 0,
    "requests_client_error": 0,
    "requests_server_error": 0,
}


def request_metrics_snapshot() -> dict[str, int]:
    return dict(REQUEST_COUNTERS)


def reset_request_metrics() -> None:
    for key in REQUEST_COUNTERS:
        REQUEST_COUNTERS[key] = 0


class CorrelationMiddleware:
    def __init__(self, app: Any, *, header: str = REQUEST_ID_HEADER) -> None:
        self._app = app
        self._header = header

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        request_id = headers.get(self._header) or uuid4().hex
        token = request_identifier.set(request_id)
        status_holder = {"status": 500}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
                message.setdefault("headers", [])
                message["headers"].append((self._header.encode("latin-1"), request_id.encode("latin-1")))
            await send(message)

        try:
            REQUEST_COUNTERS["requests_total"] += 1
            await self._app(scope, receive, send_wrapper)
        finally:
            status = status_holder["status"]
            if 400 <= status < 500:
                REQUEST_COUNTERS["requests_client_error"] += 1
            elif status >= 500:
                REQUEST_COUNTERS["requests_server_error"] += 1
            request_identifier.reset(token)
