from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from agentqa.contracts.case import FixtureReceipt
from agentqa.platform.fixtures import FixtureDefinition, FixtureRegistry, TaskboardFixture
from agentqa.platform.fixtures.runs import FixtureRunService
from agentqa.platform.storage.roles import ROLE_SUPERVISOR
from tests.support.postgres import seed_workspace

pytestmark = pytest.mark.asyncio


class FlakyCleanupHandler:
    def __init__(self, inner: TaskboardFixture) -> None:
        self._inner = inner
        self.cleanup_calls = 0

    def definition(self) -> FixtureDefinition:
        return self._inner.definition()

    def prepare(self, namespace: str, seed: str | None = None) -> FixtureReceipt:
        return self._inner.prepare(namespace, seed)

    def reset(self, namespace: str) -> FixtureReceipt:
        return self._inner.reset(namespace)

    def cleanup(self, namespace: str) -> FixtureReceipt:
        self.cleanup_calls += 1
        return FixtureReceipt(
            fixture_ref=self._inner.definition().ref(),
            namespace=namespace,
            action="cleanup",
            ok=False,
            detail="fault-injected cleanup failure",
        )

    def probe(self, namespace: str) -> dict[str, Any]:
        return self._inner.probe(namespace)

    def state(self, namespace: str) -> dict[str, Any]:
        return self._inner.state(namespace)


async def test_cleanup_exhaustion_records_bounded_attempts(role_engines) -> None:
    engines = role_engines
    user_id, workspace_id = await seed_workspace(engines, label=f"cleanup-fault-{uuid4().hex[:8]}")
    handler = FlakyCleanupHandler(TaskboardFixture("http://127.0.0.1:1", "token-khong-dung"))
    registry = FixtureRegistry()
    registry.register(handler)
    max_attempts = 3
    service = FixtureRunService(
        engines[ROLE_SUPERVISOR],
        registry=registry,
        max_attempts=max_attempts,
        backoff_seconds=0,
    )
    record_id = await service.enqueue_cleanup(
        workspace_id=workspace_id,
        principal_id=user_id,
        run_id=None,
        execution_id=None,
        attempt_id=None,
        fixture_ref="taskboard@1",
        namespace="cleanup-injected-failure",
    )

    states: list[list[str]] = []
    for _ in range(max_attempts + 1):
        results = await service.process_due(
            workspace_id=workspace_id, principal_id=user_id, worker_id="fixture-worker", limit=1
        )
        states.append([item["state"] for item in results])

    assert states[0] == ["pending"]
    assert states[1] == ["pending"]
    assert states[2] == ["exhausted"]
    assert states[3] == []
    assert handler.cleanup_calls == max_attempts

    rows = await service.claim_due(workspace_id=workspace_id, principal_id=user_id, worker_id="fixture-worker")
    assert rows == []
    assert record_id is not None
