from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.support.platform import service_workspace

from agentqa.platform.outbox import OutboxService
from agentqa.platform.outbox.service import DELIVERY_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio

SECRET = "webhook-secret-canary"


class LocalReceiver:
    def __init__(self, responses: list[int]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header_block = await reader.readuntil(b"\r\n\r\n")
        lines = header_block.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0") or "0")
        body = await reader.readexactly(length) if length else b""
        self.requests.append({"headers": headers, "body": body})
        status = self._responses.pop(0) if self._responses else 200
        reason = "OK" if status == 200 else "Server Error"
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        writer.close()


async def _setup(runtime, receiver: LocalReceiver) -> tuple:
    user_id, username, workspace_id = await service_workspace(runtime)
    api_service = OutboxService(
        runtime.engines[ROLE_API], authorization=runtime.authorization, credentials=runtime.credentials
    )
    endpoint_id = await api_service.register_endpoint(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        url=f"http://127.0.0.1:{receiver.port}/hook",
        secret=SECRET,
    )
    worker_service = OutboxService(runtime.engines[ROLE_WORKER], credentials=runtime.credentials)
    return api_service, worker_service, user_id, workspace_id, endpoint_id


async def test_delivery_signs_payload_and_retries_idempotently(runtime) -> None:
    receiver = LocalReceiver([500, 200])
    await receiver.start()
    try:
        api_service, worker_service, user_id, workspace_id, endpoint_id = await _setup(runtime, receiver)
        delivery_id = await api_service.enqueue(
            workspace_id=workspace_id,
            principal_id=user_id,
            endpoint_id=endpoint_id,
            topic="run.completed",
            payload={"run_id": "run-1", "verdict": "passed"},
            dedupe_key=f"hook-{uuid4().hex}",
        )
        base = datetime.now(UTC)
        first = await worker_service.deliver_due(
            workspace_id=workspace_id, principal_id=user_id, worker_id="w1", now=base
        )
        assert first[0].state == "pending"
        assert first[0].attempts == 1
        second = await worker_service.deliver_due(
            workspace_id=workspace_id,
            principal_id=user_id,
            worker_id="w1",
            now=base + timedelta(seconds=10),
        )
        assert second[0].state == "delivered"
        assert second[0].attempts == 2
        assert len(receiver.requests) == 2
        for request in receiver.requests:
            headers = request["headers"]
            assert headers[DELIVERY_HEADER.lower()] == str(delivery_id)
            timestamp = int(headers[TIMESTAMP_HEADER.lower()])
            expected = (
                "sha256="
                + hmac.new(SECRET.encode(), f"{timestamp}.".encode() + request["body"], hashlib.sha256).hexdigest()
            )
            assert headers[SIGNATURE_HEADER.lower()] == expected
            assert json.loads(request["body"]) == {"run_id": "run-1", "verdict": "passed"}
        assert (
            receiver.requests[0]["headers"][DELIVERY_HEADER.lower()]
            == receiver.requests[1]["headers"][DELIVERY_HEADER.lower()]
        )
    finally:
        await receiver.stop()


async def test_delivery_retries_are_bounded_then_failed(runtime) -> None:
    receiver = LocalReceiver([500, 500, 500, 200])
    await receiver.start()
    try:
        api_service, worker_service, user_id, workspace_id, endpoint_id = await _setup(runtime, receiver)
        await api_service.enqueue(
            workspace_id=workspace_id,
            principal_id=user_id,
            endpoint_id=endpoint_id,
            topic="run.completed",
            payload={"run_id": "run-2"},
            dedupe_key=f"hook-{uuid4().hex}",
        )
        base = datetime.now(UTC)
        states = []
        for index in range(3):
            results = await worker_service.deliver_due(
                workspace_id=workspace_id,
                principal_id=user_id,
                worker_id="w1",
                now=base + timedelta(seconds=60 * index),
            )
            states.append(results[0].state if results else None)
        assert states == ["pending", "pending", "failed"]
        more = await worker_service.deliver_due(
            workspace_id=workspace_id,
            principal_id=user_id,
            worker_id="w1",
            now=base + timedelta(seconds=600),
        )
        assert more == []
        assert len(receiver.requests) == 3
        deliveries = await api_service.list_deliveries(workspace_id=workspace_id, principal_id=user_id)
        assert deliveries[0]["state"] == "failed"
        assert deliveries[0]["attempts"] == 3
        assert deliveries[0]["last_error"] == "http 500"
    finally:
        await receiver.stop()


async def test_unreachable_receiver_records_error(runtime) -> None:
    user_id, username, workspace_id = await service_workspace(runtime)
    api_service = OutboxService(
        runtime.engines[ROLE_API], authorization=runtime.authorization, credentials=runtime.credentials
    )
    endpoint_id = await api_service.register_endpoint(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        url="http://127.0.0.1:1/hook",
        secret=SECRET,
    )
    await api_service.enqueue(
        workspace_id=workspace_id,
        principal_id=user_id,
        endpoint_id=endpoint_id,
        topic="run.completed",
        payload={"run_id": "run-3"},
        dedupe_key=f"hook-{uuid4().hex}",
    )
    worker_service = OutboxService(runtime.engines[ROLE_WORKER], credentials=runtime.credentials)
    results = await worker_service.deliver_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="w1", now=datetime.now(UTC)
    )
    assert results[0].state == "pending"
    assert (results[0].detail and "Error" in results[0].detail) or "Connect" in (results[0].detail or "")
