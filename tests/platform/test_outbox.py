from __future__ import annotations

import pytest
import sqlalchemy as sa
from tests.support.postgres import scoped_transaction

from agentqa.platform.identity.models import IdentityError
from agentqa.platform.outbox import OutboxService
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

pytestmark = pytest.mark.asyncio


async def _service(runtime) -> OutboxService:
    return OutboxService(
        runtime.engines[ROLE_API], authorization=runtime.authorization, credentials=runtime.credentials
    )


async def _endpoint(runtime, owner) -> tuple:
    user_id, username, workspace_id = owner
    service = await _service(runtime)
    endpoint_id = await service.register_endpoint(
        workspace_id=workspace_id,
        principal_id=user_id,
        actor=username,
        url="http://127.0.0.1:9/hook",
        secret="webhook-secret-one",
    )
    return service, user_id, workspace_id, endpoint_id


async def _count(runtime, workspace_id, user_id, table) -> int:
    async with scoped_transaction(
        runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
    ) as session:
        return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


async def test_enqueue_is_transactional_and_deduplicated(runtime) -> None:
    from tests.support.platform import service_workspace

    user_id, username, workspace_id = await service_workspace(runtime)
    service, user_id, workspace_id, endpoint_id = await _endpoint(runtime, (user_id, username, workspace_id))

    class Rollback(Exception):
        pass

    try:
        async with scoped_transaction(
            runtime.engines[ROLE_API], principal_id=user_id, workspace_id=workspace_id
        ) as session:
            await service.enqueue_with_session(
                session,
                workspace_id=workspace_id,
                endpoint_id=endpoint_id,
                topic="run.completed",
                payload={"run_id": "r1"},
                dedupe_key="dedupe-1",
            )
            raise Rollback()
    except Rollback:
        pass
    assert await _count(runtime, workspace_id, user_id, tables.outbox_deliveries) == 0

    first = await service.enqueue(
        workspace_id=workspace_id,
        principal_id=user_id,
        endpoint_id=endpoint_id,
        topic="run.completed",
        payload={"run_id": "r1"},
        dedupe_key="dedupe-1",
    )
    second = await service.enqueue(
        workspace_id=workspace_id,
        principal_id=user_id,
        endpoint_id=endpoint_id,
        topic="run.completed",
        payload={"run_id": "r1"},
        dedupe_key="dedupe-1",
    )
    assert first == second
    assert await _count(runtime, workspace_id, user_id, tables.outbox_deliveries) == 1
    deliveries = await service.list_deliveries(workspace_id=workspace_id, principal_id=user_id)
    assert deliveries[0]["state"] == "pending"
    assert deliveries[0]["attempts"] == 0


async def test_enqueue_rejects_unknown_endpoint_outside_allowlist(runtime) -> None:
    from uuid import uuid4

    from tests.support.platform import service_workspace

    user_id, username, workspace_id = await service_workspace(runtime)
    service = await _service(runtime)
    with pytest.raises(IdentityError):
        await service.enqueue(
            workspace_id=workspace_id,
            principal_id=user_id,
            endpoint_id=uuid4(),
            topic="run.completed",
            payload={},
            dedupe_key=f"dedupe-{uuid4().hex}",
        )
    _ = username
    assert await _count(runtime, workspace_id, user_id, tables.outbox_deliveries) == 0


async def test_delivery_worker_role_updates_state(runtime) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from tests.support.platform import service_workspace

    user_id, username, workspace_id = await service_workspace(runtime)
    api_service, user_id, workspace_id, endpoint_id = await _endpoint(runtime, (user_id, username, workspace_id))
    await api_service.enqueue(
        workspace_id=workspace_id,
        principal_id=user_id,
        endpoint_id=endpoint_id,
        topic="run.completed",
        payload={"run_id": "r2"},
        dedupe_key=f"dedupe-{uuid4().hex}",
    )
    worker_service = OutboxService(runtime.engines[ROLE_WORKER], credentials=runtime.credentials)
    results = await worker_service.deliver_due(
        workspace_id=workspace_id, principal_id=user_id, worker_id="w1", now=datetime.now(UTC)
    )
    assert len(results) == 1
    assert results[0].state == "pending"
    assert results[0].attempts == 1
    assert results[0].detail
