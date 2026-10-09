from __future__ import annotations

from typing import Any

from agentqa.contracts.case import FixtureReceipt
from agentqa.platform.fixtures.definitions import FixtureDefinition
from agentqa.platform.fixtures.taskboard import TaskboardFixture


class FixtureRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskboardFixture] = {}

    def register(self, handler: TaskboardFixture) -> None:
        definition = handler.definition()
        self._handlers[definition.fixture_id] = handler

    def _resolve(self, fixture_ref: str) -> tuple[TaskboardFixture, str] | None:
        fixture_id, _, version = fixture_ref.partition("@")
        handler = self._handlers.get(fixture_id)
        if handler is None:
            return None
        definition = handler.definition()
        if version and version != str(definition.version):
            return None
        return handler, fixture_ref

    def _unknown_ref(self, fixture_ref: str, namespace: str, action: str) -> FixtureReceipt:
        return FixtureReceipt(
            fixture_ref=fixture_ref,
            namespace=namespace,
            action=action,
            ok=False,
            detail=f"fixture '{fixture_ref}' chưa được đăng ký hoặc sai version",
        )

    def definition(self, fixture_ref: str) -> FixtureDefinition | None:
        resolved = self._resolve(fixture_ref)
        if resolved is None:
            return None
        return resolved[0].definition()

    def prepare(self, fixture_ref: str, namespace: str, seed: str = "success") -> FixtureReceipt:
        resolved = self._resolve(fixture_ref)
        if resolved is None:
            return self._unknown_ref(fixture_ref, namespace, "prepare")
        return resolved[0].prepare(namespace, seed)

    def reset(self, fixture_ref: str, namespace: str) -> FixtureReceipt:
        resolved = self._resolve(fixture_ref)
        if resolved is None:
            return self._unknown_ref(fixture_ref, namespace, "reset")
        return resolved[0].reset(namespace)

    def cleanup(self, fixture_ref: str, namespace: str) -> FixtureReceipt:
        resolved = self._resolve(fixture_ref)
        if resolved is None:
            return self._unknown_ref(fixture_ref, namespace, "cleanup")
        return resolved[0].cleanup(namespace)

    def probe(self, fixture_ref: str, namespace: str) -> dict[str, Any]:
        resolved = self._resolve(fixture_ref)
        if resolved is None:
            raise KeyError(f"fixture '{fixture_ref}' chưa được đăng ký hoặc sai version")
        return resolved[0].probe(namespace)
