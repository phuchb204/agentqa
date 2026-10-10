from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentqa.contracts.errors import ErrorCode
from agentqa.platform.identity.authorization import AuthorizationService
from agentqa.platform.identity.models import IdentityError, Permission
from agentqa.platform.security.credentials import CredentialService
from agentqa.platform.security.taint import SecurityError
from agentqa.platform.storage import tables
from agentqa.platform.storage.database import create_session_factory
from agentqa.platform.storage.scope import set_scope

SIGNATURE_HEADER = "X-AgentQA-Signature"
TIMESTAMP_HEADER = "X-AgentQA-Timestamp"
DELIVERY_HEADER = "X-AgentQA-Delivery"
DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class DeliveryResult:
    delivery_id: UUID
    state: str
    attempts: int
    detail: str | None = None


def sign_payload(secret: str, *, timestamp: int, body: bytes) -> str:
    material = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


class OutboxService:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        authorization: AuthorizationService | None = None,
        credentials: CredentialService | None = None,
        http_timeout: float = 10.0,
    ) -> None:
        self._factory = create_session_factory(engine)
        self._authorization = authorization
        self._credentials = credentials or CredentialService(_default_envelope())
        self._http_timeout = http_timeout

    async def register_endpoint(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        actor: str,
        url: str,
        secret: str,
    ) -> UUID:
        if self._authorization is not None:
            await self._authorization.require(
                workspace_id=workspace_id, user_id=principal_id, permission=Permission.SETTINGS_MANAGE
            )
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SecurityError(ErrorCode.INPUT_INVALID, "Webhook URL phải là http(s) có host")
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            endpoint_id = uuid4()
            credential = await self._credentials.create_envelope(
                session,
                workspace_id=workspace_id,
                credential_ref=f"webhook/{endpoint_id}",
                plaintext=secret,
                actor=actor,
            )
            await session.execute(
                sa.insert(tables.webhook_endpoints).values(
                    id=endpoint_id,
                    workspace_id=workspace_id,
                    url=url,
                    credential_id=credential.credential_id,
                    credential_version=credential.version,
                    enabled=True,
                )
            )
        return endpoint_id

    async def enqueue_with_session(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        endpoint_id: UUID,
        topic: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> UUID:
        endpoint = (
            await session.execute(
                sa.select(tables.webhook_endpoints.c.id).where(
                    tables.webhook_endpoints.c.workspace_id == workspace_id,
                    tables.webhook_endpoints.c.id == endpoint_id,
                    tables.webhook_endpoints.c.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if endpoint is None:
            raise IdentityError(ErrorCode.NOT_FOUND, "Webhook endpoint không tồn tại trong scope hoặc đã tắt")
        inserted = (
            await session.execute(
                pg_insert(tables.outbox_deliveries)
                .values(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    topic=topic,
                    dedupe_key=dedupe_key,
                    endpoint_id=endpoint_id,
                    payload=payload,
                    state="pending",
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(tables.outbox_deliveries.c.id)
            )
        ).scalar_one_or_none()
        if inserted is not None:
            return inserted
        existing = (
            await session.execute(
                sa.select(tables.outbox_deliveries.c.id).where(tables.outbox_deliveries.c.dedupe_key == dedupe_key)
            )
        ).scalar_one()
        return existing

    async def enqueue(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        endpoint_id: UUID,
        topic: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> UUID:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            return await self.enqueue_with_session(
                session,
                workspace_id=workspace_id,
                endpoint_id=endpoint_id,
                topic=topic,
                payload=payload,
                dedupe_key=dedupe_key,
            )

    async def deliver_due(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        worker_id: str,
        limit: int = 10,
        now: datetime | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> list[DeliveryResult]:
        moment = now or datetime.now(UTC)
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.outbox_deliveries)
                    .where(
                        tables.outbox_deliveries.c.workspace_id == workspace_id,
                        tables.outbox_deliveries.c.state == "pending",
                        tables.outbox_deliveries.c.endpoint_id.is_not(None),
                        tables.outbox_deliveries.c.available_at <= moment,
                    )
                    .order_by(tables.outbox_deliveries.c.available_at, tables.outbox_deliveries.c.id)
                    .limit(limit)
                )
            ).all()
            endpoints = (
                await session.execute(
                    sa.select(tables.webhook_endpoints).where(
                        tables.webhook_endpoints.c.workspace_id == workspace_id,
                        tables.webhook_endpoints.c.id.in_([row.endpoint_id for row in rows]),
                    )
                )
            ).all()
            secrets: dict[UUID, str] = {}
            for endpoint in endpoints:
                try:
                    value = await self._credentials.resolve(
                        session,
                        workspace_id=workspace_id,
                        credential_id=endpoint.credential_id,
                        version=endpoint.credential_version,
                    )
                except SecurityError:
                    continue
                secrets[endpoint.id] = value.reveal()
            endpoint_map = {endpoint.id: endpoint for endpoint in endpoints}
        results: list[DeliveryResult] = []
        for row in rows:
            endpoint = endpoint_map.get(row.endpoint_id)
            secret = secrets.get(row.endpoint_id)
            if endpoint is None or secret is None:
                results.append(
                    await self._settle(
                        workspace_id=workspace_id,
                        principal_id=principal_id,
                        delivery_id=row.id,
                        attempts=row.attempts,
                        max_attempts=row.max_attempts,
                        ok=False,
                        detail="endpoint_unavailable",
                    )
                )
                continue
            body = json.dumps(row.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            timestamp = int(moment.timestamp())
            headers = {
                "Content-Type": "application/json",
                DELIVERY_HEADER: str(row.id),
                TIMESTAMP_HEADER: str(timestamp),
                SIGNATURE_HEADER: sign_payload(secret, timestamp=timestamp, body=body),
            }
            try:
                async with httpx.AsyncClient(timeout=self._http_timeout, transport=transport) as client:
                    response = await client.post(endpoint.url, content=body, headers=headers)
                ok = 200 <= response.status_code < 300
                detail = None if ok else f"http {response.status_code}"
            except httpx.HTTPError as error:
                ok = False
                detail = f"{type(error).__name__}"
            results.append(
                await self._settle(
                    workspace_id=workspace_id,
                    principal_id=principal_id,
                    delivery_id=row.id,
                    attempts=row.attempts,
                    max_attempts=row.max_attempts,
                    ok=ok,
                    detail=detail,
                )
            )
        _ = worker_id
        return results

    async def _settle(
        self,
        *,
        workspace_id: UUID,
        principal_id: UUID,
        delivery_id: UUID,
        attempts: int,
        max_attempts: int,
        ok: bool,
        detail: str | None,
    ) -> DeliveryResult:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            if ok:
                await session.execute(
                    sa.update(tables.outbox_deliveries)
                    .where(tables.outbox_deliveries.c.id == delivery_id)
                    .values(
                        state="delivered",
                        attempts=attempts + 1,
                        delivered_at=datetime.now(UTC),
                        last_error=None,
                    )
                )
                return DeliveryResult(delivery_id=delivery_id, state="delivered", attempts=attempts + 1)
            attempts_next = attempts + 1
            state = "failed" if attempts_next >= max_attempts else "pending"
            backoff = min(30, 2 * attempts_next)
            await session.execute(
                sa.update(tables.outbox_deliveries)
                .where(tables.outbox_deliveries.c.id == delivery_id)
                .values(
                    state=state,
                    attempts=attempts_next,
                    last_error=detail,
                    available_at=sa.text(f"now() + interval '{backoff} seconds'"),
                )
            )
            return DeliveryResult(delivery_id=delivery_id, state=state, attempts=attempts_next, detail=detail)

    async def list_deliveries(self, *, workspace_id: UUID, principal_id: UUID) -> list[dict[str, Any]]:
        async with self._factory() as session, session.begin():
            await set_scope(session, principal_id=principal_id, workspace_id=workspace_id)
            rows = (
                await session.execute(
                    sa.select(tables.outbox_deliveries)
                    .where(tables.outbox_deliveries.c.workspace_id == workspace_id)
                    .order_by(tables.outbox_deliveries.c.created_at, tables.outbox_deliveries.c.id)
                )
            ).all()
        return [
            {
                "delivery_id": row.id,
                "topic": row.topic,
                "state": row.state,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "endpoint_id": row.endpoint_id,
            }
            for row in rows
        ]


def _default_envelope():
    from agentqa.platform.security.credentials import EnvelopeService, MasterKeyring

    return EnvelopeService(MasterKeyring.synthetic())
