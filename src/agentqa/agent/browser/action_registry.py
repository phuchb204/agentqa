from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from agentqa.agent.browser.capture import REDACTED, SafeEvidenceService
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.contracts.actions import (
    ActionCommand,
    ActionOutcome,
    ActionReceipt,
    ActionState,
    Operation,
    SideEffectClass,
)
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import CaptureValue, LiteralValue, ParameterValue, SecretValue, SensitiveValue

ACTION_TIMEOUT_MS = 5000

SIDE_EFFECTS: dict[Operation, SideEffectClass] = {
    Operation.NAVIGATE: SideEffectClass.READ,
    Operation.WAIT: SideEffectClass.READ,
    Operation.FILL: SideEffectClass.REVERSIBLE,
    Operation.CLICK: SideEffectClass.EXTERNAL_WRITE,
}


class CapabilityUnavailable(Exception):
    def __init__(self, operation: Operation) -> None:
        self.operation = operation
        super().__init__(f"operation '{operation.value}' chưa được implement")


class SecretResolver(Protocol):
    def resolve(self, grant_ref: str) -> SensitiveValue: ...


class NavigationGuard(Protocol):
    def check_url(self, url: str) -> object: ...


@dataclass(frozen=True)
class ActionCapability:
    operation: Operation
    implemented: bool
    requires_target: bool
    requires_value: bool


def build_capability_registry() -> dict[Operation, ActionCapability]:
    implemented: dict[Operation, tuple[bool, bool]] = {
        Operation.NAVIGATE: (False, True),
        Operation.CLICK: (True, False),
        Operation.FILL: (True, True),
        Operation.WAIT: (False, False),
    }
    registry: dict[Operation, ActionCapability] = {}
    for operation in Operation:
        requires_target, requires_value = implemented.get(operation, (False, False))
        registry[operation] = ActionCapability(
            operation=operation,
            implemented=operation in implemented,
            requires_target=requires_target,
            requires_value=requires_value,
        )
    return registry


def build_locator(page: Page, target: TargetDescriptor) -> Locator | None:
    base: Locator | None = None
    if target.locators:
        alternative = target.locators[0]
        if alternative.kind.value == "role":
            base = page.get_by_role(alternative.value)
        elif alternative.kind.value == "label":
            base = page.get_by_label(alternative.value)
        elif alternative.kind.value == "text":
            base = page.get_by_text(alternative.value)
        elif alternative.kind.value == "test_id":
            base = page.get_by_test_id(alternative.value)
        else:
            base = page.locator(alternative.value)
    elif target.role and target.name:
        base = page.get_by_role(target.role, name=target.name, exact=True)
    elif target.role:
        base = page.get_by_role(target.role)
    elif target.name:
        base = page.get_by_text(target.name, exact=True)
    if target.attributes:
        css = "".join(f'[{name}="{value}"]' for name, value in sorted(target.attributes.items()))
        attribute_locator = page.locator(css)
        base = base.and_(attribute_locator) if base is not None else attribute_locator
    if (
        target.entity_scope is not None
        and isinstance(target.entity_scope.value, LiteralValue)
        and isinstance(target.entity_scope.value.value, str)
    ):
        scope_root = page.locator("li", has_text=target.entity_scope.value.value)
        if target.role == "listitem" and target.name is None:
            base = scope_root
        elif target.role and target.name:
            base = scope_root.get_by_role(target.role, name=target.name, exact=True)
        elif target.name:
            base = scope_root.get_by_text(target.name, exact=True)
        elif target.role:
            base = scope_root.get_by_role(target.role)
        else:
            base = scope_root
    return base


class PlaywrightActionPort:
    def __init__(
        self,
        contexts: ContextRegistry,
        evidence: SafeEvidenceService,
        secret_resolver: SecretResolver | None = None,
        navigation_guard: NavigationGuard | None = None,
        context_key_resolver: Callable[[ActionCommand], str] | None = None,
    ) -> None:
        self._contexts = contexts
        self._evidence = evidence
        self._secret_resolver = secret_resolver
        self._navigation_guard = navigation_guard
        self._context_key_resolver = context_key_resolver or _context_key_for
        self._capabilities = build_capability_registry()
        self._receipts: dict[UUID, ActionReceipt] = {}

    def capability(self, operation: Operation) -> ActionCapability:
        return self._capabilities[operation]

    @property
    def supported_operations(self) -> tuple[Operation, ...]:
        return tuple(operation for operation, capability in self._capabilities.items() if capability.implemented)

    async def query_outcome(self, command_id: UUID) -> ActionReceipt:
        receipt = self._receipts.get(command_id)
        if receipt is not None:
            return receipt
        return _receipt(
            command_id=command_id,
            outcome=ActionOutcome.UNKNOWN,
            side_effect=SideEffectClass.READ,
            evidence_refs=["no_receipt"],
        )

    async def dispatch(self, command: ActionCommand) -> ActionReceipt:
        cached = self._receipts.get(command.command_id)
        if cached is not None:
            return cached
        capability = self._capabilities[command.operation]
        if not capability.implemented:
            return self._store(
                command,
                _receipt(
                    command_id=command.command_id,
                    outcome=ActionOutcome.REJECTED,
                    side_effect=SIDE_EFFECTS.get(command.operation, SideEffectClass.READ),
                    evidence_refs=["capability_unavailable"],
                ),
            )
        lane = self._contexts.lane(self._context_key_resolver(command))
        if command.expected_observation_version != lane.observation_version:
            return self._store(
                command,
                _receipt(
                    command_id=command.command_id,
                    outcome=ActionOutcome.REJECTED,
                    side_effect=SIDE_EFFECTS.get(command.operation, SideEffectClass.READ),
                    evidence_refs=["scene_stale"],
                ),
            )
        if capability.requires_target and command.target is None:
            return self._store(command, _rejected(command, "target_missing"))
        if capability.requires_value and command.value is None:
            return self._store(command, _rejected(command, "value_missing"))
        try:
            return self._store(command, await self._execute(command, lane.context_key))
        except PlaywrightTimeoutError:
            return self._store(command, _failed(command, "action_timeout"))
        except Exception as exc:
            return self._store(command, _failed(command, f"action_error:{type(exc).__name__}"))

    async def _execute(self, command: ActionCommand, context_key: str) -> ActionReceipt:
        page = await self._contexts.page(context_key)
        if command.operation == Operation.NAVIGATE:
            assert isinstance(command.value, LiteralValue)
            url = command.value.value
            assert isinstance(url, str)
            if self._navigation_guard is not None:
                try:
                    self._navigation_guard.check_url(url)
                except Exception:
                    return _rejected(command, "egress_denied")
            await page.goto(url, wait_until="domcontentloaded", timeout=ACTION_TIMEOUT_MS)
            self._evidence.record_action({"operation": "navigate", "url": self._evidence.sanitize_url(url)})
            return _receipt(
                command_id=command.command_id,
                outcome=ActionOutcome.SUCCEEDED,
                side_effect=SideEffectClass.READ,
                observed_target=command.target,
                evidence_refs=["navigate:ok"],
            )
        if command.operation == Operation.CLICK:
            assert command.target is not None
            locator = build_locator(page, command.target)
            assert locator is not None
            outcome, ref = await _guard_locator(locator)
            if outcome is not None:
                return _rejected(command, ref)
            await locator.click(timeout=ACTION_TIMEOUT_MS)
            self._evidence.record_action({"operation": "click", "target": command.target.intent})
            return _receipt(
                command_id=command.command_id,
                outcome=ActionOutcome.SUCCEEDED,
                side_effect=SideEffectClass.EXTERNAL_WRITE,
                observed_target=command.target,
                evidence_refs=["click:ok"],
            )
        if command.operation == Operation.FILL:
            assert command.target is not None
            locator = build_locator(page, command.target)
            assert locator is not None
            outcome, ref = await _guard_locator(locator)
            if outcome is not None:
                return _rejected(command, ref)
            if isinstance(command.value, SecretValue):
                secret = self._resolve_secret(command, command.value.credential_ref)
                if secret is None:
                    return _rejected(command, "secret_grant_missing")
                await locator.fill(secret.reveal(), timeout=ACTION_TIMEOUT_MS)
                self._evidence.register_secret(secret.reveal())
                self._evidence.record_action(
                    {"operation": "fill", "target": command.target.intent, "value": REDACTED, "taint": "secret"}
                )
                return _receipt(
                    command_id=command.command_id,
                    outcome=ActionOutcome.SUCCEEDED,
                    side_effect=SideEffectClass.REVERSIBLE,
                    observed_target=command.target,
                    evidence_refs=["fill:secret_redacted"],
                )
            literal = _text_value(command.value)
            if literal is None:
                return _rejected(command, "value_unsupported")
            await locator.fill(literal, timeout=ACTION_TIMEOUT_MS)
            self._evidence.record_action({"operation": "fill", "target": command.target.intent, "value": literal})
            return _receipt(
                command_id=command.command_id,
                outcome=ActionOutcome.SUCCEEDED,
                side_effect=SideEffectClass.REVERSIBLE,
                observed_target=command.target,
                evidence_refs=["fill:ok"],
            )
        if command.operation == Operation.WAIT:
            if command.target is None:
                await asyncio.sleep(0.5)
                return _receipt(
                    command_id=command.command_id,
                    outcome=ActionOutcome.SUCCEEDED,
                    side_effect=SideEffectClass.READ,
                    evidence_refs=["wait:elapsed"],
                )
            locator = build_locator(page, command.target)
            assert locator is not None
            await locator.first.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
            return _receipt(
                command_id=command.command_id,
                outcome=ActionOutcome.SUCCEEDED,
                side_effect=SideEffectClass.READ,
                observed_target=command.target,
                evidence_refs=["wait:visible"],
            )
        return _rejected(command, "operation_unhandled")

    def _resolve_secret(self, command: ActionCommand, credential_ref: str) -> SensitiveValue | None:
        if self._secret_resolver is None:
            return None
        grant_ref = command.secret_grant_refs[0] if command.secret_grant_refs else credential_ref
        return self._secret_resolver.resolve(grant_ref)

    def _store(self, command: ActionCommand, receipt: ActionReceipt) -> ActionReceipt:
        self._receipts[command.command_id] = receipt
        return receipt


def _context_key_for(command: ActionCommand) -> str:
    return str(command.run_id)


def _text_value(value: object) -> str | None:
    if isinstance(value, LiteralValue) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ParameterValue):
        return None
    if isinstance(value, CaptureValue):
        return None
    return None


async def _guard_locator(locator: Locator) -> tuple[ActionOutcome | None, str]:
    count = await locator.count()
    if count == 0:
        return ActionOutcome.REJECTED, "locator_missing"
    if count > 1:
        return ActionOutcome.REJECTED, "locator_ambiguous"
    return None, ""


def _rejected(command: ActionCommand, ref: str) -> ActionReceipt:
    return _receipt(
        command_id=command.command_id,
        outcome=ActionOutcome.REJECTED,
        side_effect=SIDE_EFFECTS.get(command.operation, SideEffectClass.READ),
        observed_target=command.target,
        evidence_refs=[ref],
    )


def _failed(command: ActionCommand, ref: str) -> ActionReceipt:
    return _receipt(
        command_id=command.command_id,
        outcome=ActionOutcome.FAILED,
        side_effect=SIDE_EFFECTS.get(command.operation, SideEffectClass.READ),
        observed_target=command.target,
        evidence_refs=[ref],
    )


def _receipt(
    command_id: UUID,
    outcome: ActionOutcome,
    side_effect: SideEffectClass,
    observed_target: TargetDescriptor | None = None,
    evidence_refs: list[str] | None = None,
) -> ActionReceipt:
    return ActionReceipt(
        command_id=command_id,
        state=ActionState.ACCEPTED if outcome == ActionOutcome.SUCCEEDED else ActionState.PROPOSED,
        outcome=outcome,
        side_effect=side_effect,
        observed_target=observed_target,
        evidence_refs=evidence_refs or [],
        recorded_at=datetime.now(UTC),
    )
