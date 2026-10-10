from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID

from playwright.async_api import Frame, Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from agentqa.agent.browser.capture import REDACTED, SafeEvidenceService
from agentqa.agent.browser.contexts import ContextRegistry, DialogPolicy
from agentqa.agent.browser.journals import DownloadJournal, DownloadRecord
from agentqa.contracts.actions import (
    ActionCommand,
    ActionOutcome,
    ActionReceipt,
    ActionState,
    Operation,
    SideEffectClass,
)
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue, SensitiveValue

ACTION_TIMEOUT_MS = 5000
DOWNLOAD_TIMEOUT_MS = 8000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

SIDE_EFFECTS: dict[Operation, SideEffectClass] = {
    Operation.NAVIGATE: SideEffectClass.READ,
    Operation.WAIT: SideEffectClass.READ,
    Operation.HOVER: SideEffectClass.READ,
    Operation.SCROLL: SideEffectClass.READ,
    Operation.SWITCH_PAGE: SideEffectClass.READ,
    Operation.SWITCH_FRAME: SideEffectClass.READ,
    Operation.EXPECT_DOWNLOAD: SideEffectClass.READ,
    Operation.FILL: SideEffectClass.REVERSIBLE,
    Operation.TYPE: SideEffectClass.REVERSIBLE,
    Operation.CLEAR: SideEffectClass.REVERSIBLE,
    Operation.PRESS: SideEffectClass.REVERSIBLE,
    Operation.CHECK: SideEffectClass.REVERSIBLE,
    Operation.UNCHECK: SideEffectClass.REVERSIBLE,
    Operation.SELECT: SideEffectClass.REVERSIBLE,
    Operation.UPLOAD: SideEffectClass.REVERSIBLE,
    Operation.HANDLE_DIALOG: SideEffectClass.READ,
    Operation.CLICK: SideEffectClass.EXTERNAL_WRITE,
    Operation.DOUBLE_CLICK: SideEffectClass.EXTERNAL_WRITE,
}

TARGET_OPS = frozenset(
    {
        Operation.CLICK,
        Operation.DOUBLE_CLICK,
        Operation.FILL,
        Operation.TYPE,
        Operation.CLEAR,
        Operation.PRESS,
        Operation.CHECK,
        Operation.UNCHECK,
        Operation.SELECT,
        Operation.HOVER,
        Operation.UPLOAD,
    }
)
VALUE_OPS = frozenset(
    {
        Operation.FILL,
        Operation.TYPE,
        Operation.PRESS,
        Operation.SELECT,
        Operation.UPLOAD,
        Operation.NAVIGATE,
        Operation.SWITCH_PAGE,
        Operation.SWITCH_FRAME,
        Operation.HANDLE_DIALOG,
    }
)


class CapabilityUnavailable(Exception):
    def __init__(self, operation: Operation) -> None:
        self.operation = operation
        super().__init__(f"operation '{operation.value}' chưa được implement")


class SecretResolver(Protocol):
    def resolve(self, grant_ref: str) -> SensitiveValue: ...


class NavigationGuard(Protocol):
    def check_url(self, url: str) -> object: ...


class FileResolver(Protocol):
    def resolve(self, file_id: str) -> Path: ...


@dataclass(frozen=True)
class ActionCapability:
    operation: Operation
    implemented: bool
    requires_target: bool
    requires_value: bool


def build_capability_registry() -> dict[Operation, ActionCapability]:
    registry: dict[Operation, ActionCapability] = {}
    for operation in Operation:
        registry[operation] = ActionCapability(
            operation=operation,
            implemented=True,
            requires_target=operation in TARGET_OPS,
            requires_value=operation in VALUE_OPS,
        )
    return registry


def build_locator(root: Page | Frame, target: TargetDescriptor) -> Locator | None:
    base: Locator | None = None
    if target.locators:
        alternative = target.locators[0]
        if alternative.kind.value == "role":
            base = root.get_by_role(alternative.value)
        elif alternative.kind.value == "label":
            base = root.get_by_label(alternative.value)
        elif alternative.kind.value == "text":
            base = root.get_by_text(alternative.value)
        elif alternative.kind.value == "test_id":
            base = root.get_by_test_id(alternative.value)
        else:
            base = root.locator(alternative.value)
    elif target.role and target.name:
        base = root.get_by_role(target.role, name=target.name, exact=True)
    elif target.role:
        base = root.get_by_role(target.role)
    elif target.name:
        base = root.get_by_text(target.name, exact=True)
    if target.attributes:
        css = "".join(f'[{name}="{value}"]' for name, value in sorted(target.attributes.items()))
        attribute_locator = root.locator(css)
        base = base.and_(attribute_locator) if base is not None else attribute_locator
    if (
        target.entity_scope is not None
        and isinstance(target.entity_scope.value, LiteralValue)
        and isinstance(target.entity_scope.value.value, str)
    ):
        scope_root = root.locator("li", has_text=target.entity_scope.value.value)
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
        file_resolver: FileResolver | None = None,
        downloads: DownloadJournal | None = None,
        context_key_resolver: Callable[[ActionCommand], str] | None = None,
    ) -> None:
        self._contexts = contexts
        self._evidence = evidence
        self._secret_resolver = secret_resolver
        self._navigation_guard = navigation_guard
        self._file_resolver = file_resolver
        self._downloads = downloads or DownloadJournal()
        self._context_key_resolver = context_key_resolver or _context_key_for
        self._capabilities = build_capability_registry()
        self._receipts: dict[UUID, ActionReceipt] = {}
        self._pending_downloads: dict[str, list] = {}
        self._watched_pages: set[int] = set()

    def capability(self, operation: Operation) -> ActionCapability:
        return self._capabilities[operation]

    @property
    def supported_operations(self) -> tuple[Operation, ...]:
        return tuple(operation for operation, capability in self._capabilities.items() if capability.implemented)

    @property
    def downloads(self) -> DownloadJournal:
        return self._downloads

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
            return self._store(command, _rejected(command, "capability_unavailable"))
        context_key = self._context_key_resolver(command)
        lane = self._contexts.lane(context_key)
        if command.expected_observation_version != lane.observation_version:
            return self._store(command, _rejected(command, "scene_stale"))
        if capability.requires_target and command.target is None:
            return self._store(command, _rejected(command, "target_missing"))
        if capability.requires_value and command.value is None:
            return self._store(command, _rejected(command, "value_missing"))
        if lane.unhandled_dialogs:
            reason = lane.unhandled_dialogs.pop(0)
            return self._store(command, _rejected(command, f"dialog_outside_rule:{reason}"))
        try:
            return self._store(command, await self._execute(command, context_key))
        except PlaywrightTimeoutError:
            return self._store(command, _failed(command, "action_timeout"))
        except Exception as exc:
            return self._store(command, _failed(command, f"action_error:{type(exc).__name__}"))

    async def _execute(self, command: ActionCommand, context_key: str) -> ActionReceipt:
        lane = self._contexts.lane(context_key)
        page = await self._contexts.page(context_key, command.page_key)
        self._watch_downloads(context_key, page)
        if command.operation == Operation.SWITCH_PAGE:
            return await self._switch_page(command, context_key)
        if command.operation == Operation.SWITCH_FRAME:
            return await self._switch_frame(command, context_key)
        if command.operation == Operation.HANDLE_DIALOG:
            return self._handle_dialog_rule(command, lane)
        if command.operation == Operation.EXPECT_DOWNLOAD:
            return await self._expect_download(command, context_key)
        if command.operation == Operation.NAVIGATE:
            return await self._navigate(command, page)
        root = await self._contexts.locator_root(context_key, command.page_key)
        if command.operation == Operation.CLICK:
            return await self._click_like(command, root, "click")
        if command.operation == Operation.DOUBLE_CLICK:
            return await self._click_like(command, root, "dblclick")
        if command.operation == Operation.HOVER:
            return await self._click_like(command, root, "hover")
        if command.operation == Operation.FILL:
            return await self._fill(command, root)
        if command.operation == Operation.TYPE:
            return await self._type(command, root)
        if command.operation == Operation.CLEAR:
            return await self._clear(command, root)
        if command.operation == Operation.PRESS:
            return await self._press(command, root)
        if command.operation == Operation.CHECK:
            return await self._check_like(command, root, check=True)
        if command.operation == Operation.UNCHECK:
            return await self._check_like(command, root, check=False)
        if command.operation == Operation.SELECT:
            return await self._select(command, root)
        if command.operation == Operation.SCROLL:
            return await self._scroll(command, root, page)
        if command.operation == Operation.UPLOAD:
            return await self._upload(command, root)
        if command.operation == Operation.WAIT:
            return await self._wait(command, root)
        return _rejected(command, "operation_unhandled")

    async def _navigate(self, command: ActionCommand, page: Page) -> ActionReceipt:
        url = _string_value(command.value)
        if url is None:
            return _rejected(command, "value_unsupported")
        if self._navigation_guard is not None:
            try:
                self._navigation_guard.check_url(url)
            except Exception:
                return _rejected(command, "egress_denied")
        await page.goto(url, wait_until="domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "navigate", "url": self._evidence.sanitize_url(url)})
        return _ok(command, SideEffectClass.READ, "navigate:ok")

    async def _switch_page(self, command: ActionCommand, context_key: str) -> ActionReceipt:
        page_key = _string_value(command.value)
        if page_key is None:
            return _rejected(command, "value_unsupported")
        lane = self._contexts.lane(context_key)
        pages = lane.context.pages
        if len(pages) < 2:
            return _rejected(command, "page_not_found")
        target_page = pages[-1]
        try:
            await self._contexts.bind_page(context_key, page_key, target_page)
        except Exception:
            return _rejected(command, "page_origin_mismatch")
        return _ok(command, SideEffectClass.READ, f"switch_page:{page_key}")

    async def _switch_frame(self, command: ActionCommand, context_key: str) -> ActionReceipt:
        frame_key = _string_value(command.value)
        if frame_key is None:
            return _rejected(command, "value_unsupported")
        lane = self._contexts.lane(context_key)
        if frame_key == "main":
            lane.active_frame_key = None
            return _ok(command, SideEffectClass.READ, "switch_frame:main")
        try:
            await self._contexts.frame(context_key, command.page_key, frame_key)
        except Exception:
            return _rejected(command, "frame_not_found")
        lane.active_frame_key = frame_key
        return _ok(command, SideEffectClass.READ, f"switch_frame:{frame_key}")

    def _handle_dialog_rule(self, command: ActionCommand, lane) -> ActionReceipt:
        payload = command.value
        if not isinstance(payload, LiteralValue) or not isinstance(payload.value, dict):
            return _rejected(command, "value_unsupported")
        rule = payload.value
        action = str(rule.get("action", "accept"))
        if action not in ("accept", "dismiss"):
            return _rejected(command, "dialog_rule_invalid")
        expected_prompt = rule.get("expected_prompt")
        prompt_text = rule.get("prompt_text")
        lane.dialog_policy = DialogPolicy(
            action=action,
            expected_prompt=str(expected_prompt) if expected_prompt else None,
            prompt_text=str(prompt_text) if prompt_text else None,
        )
        return _ok(command, SideEffectClass.READ, f"dialog_rule:{action}")

    async def _expect_download(self, command: ActionCommand, context_key: str) -> ActionReceipt:
        deadline = asyncio.get_running_loop().time() + DOWNLOAD_TIMEOUT_MS / 1000
        pending = self._pending_downloads.setdefault(context_key, [])
        while not pending:
            if asyncio.get_running_loop().time() >= deadline:
                return _rejected(command, "download_missing")
            await asyncio.sleep(0.05)
        download = pending.pop(0)
        try:
            path = await download.path()
            data = Path(path).read_bytes()
        except Exception:
            return _failed(command, "download_failed")
        filename = download.suggested_filename or "download.bin"
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        digest = sha256(data).hexdigest()
        artifact_ref = self._evidence.emit_file(f"download:{filename}", data, media_type)
        self._downloads.record(
            context_key,
            DownloadRecord(
                filename=filename,
                media_type=media_type,
                size_bytes=len(data),
                sha256=digest,
                artifact_ref=artifact_ref,
            ),
        )
        return _ok(command, SideEffectClass.READ, f"download:{filename}:{digest[:12]}")

    async def _click_like(self, command: ActionCommand, root, action: str) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        if action == "dblclick":
            await locator.dblclick(timeout=ACTION_TIMEOUT_MS)
        elif action == "hover":
            await locator.hover(timeout=ACTION_TIMEOUT_MS)
        else:
            await locator.click(timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": action, "target": command.target.intent})
        side_effect = SideEffectClass.EXTERNAL_WRITE if action in ("click", "dblclick") else SideEffectClass.READ
        return _ok(command, side_effect, f"{action}:ok")

    async def _fill(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        from agentqa.contracts.values import SecretValue

        if isinstance(command.value, SecretValue):
            secret = self._resolve_secret(command, command.value.credential_ref)
            if secret is None:
                return _rejected(command, "secret_grant_missing")
            await locator.fill(secret.reveal(), timeout=ACTION_TIMEOUT_MS)
            self._evidence.register_secret(secret.reveal())
            self._evidence.record_action(
                {"operation": "fill", "target": command.target.intent, "value": REDACTED, "taint": "secret"}
            )
            return _ok(command, SideEffectClass.REVERSIBLE, "fill:secret_redacted")
        literal = _string_value(command.value)
        if literal is None:
            return _rejected(command, "value_unsupported")
        await locator.fill(literal, timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "fill", "target": command.target.intent, "value": literal})
        return _ok(command, SideEffectClass.REVERSIBLE, "fill:ok")

    async def _type(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        text = _string_value(command.value)
        if text is None:
            return _rejected(command, "value_unsupported")
        await locator.press_sequentially(text, delay=0, timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "type", "target": command.target.intent, "value": text})
        return _ok(command, SideEffectClass.REVERSIBLE, "type:ok")

    async def _clear(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        await locator.clear(timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "clear", "target": command.target.intent})
        return _ok(command, SideEffectClass.REVERSIBLE, "clear:ok")

    async def _press(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        key = _string_value(command.value)
        if key is None:
            return _rejected(command, "value_unsupported")
        await locator.press(key, timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "press", "target": command.target.intent, "key": key})
        return _ok(command, SideEffectClass.REVERSIBLE, f"press:{key}")

    async def _check_like(self, command: ActionCommand, root, *, check: bool) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        if check:
            await locator.check(timeout=ACTION_TIMEOUT_MS)
        else:
            await locator.uncheck(timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "check" if check else "uncheck", "target": command.target.intent})
        return _ok(command, SideEffectClass.REVERSIBLE, "check:ok" if check else "uncheck:ok")

    async def _select(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        value = _string_value(command.value)
        if value is None:
            return _rejected(command, "value_unsupported")
        await locator.select_option(value=value, timeout=ACTION_TIMEOUT_MS)
        self._evidence.record_action({"operation": "select", "target": command.target.intent, "value": value})
        return _ok(command, SideEffectClass.REVERSIBLE, f"select:{value}")

    async def _scroll(self, command: ActionCommand, root, page: Page) -> ActionReceipt:
        if command.target is not None:
            locator = await self._single_locator(command, root)
            if isinstance(locator, ActionReceipt):
                return locator
            await locator.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            return _ok(command, SideEffectClass.READ, "scroll:target")
        amount = _int_value(command.value)
        if amount is None:
            return _rejected(command, "value_unsupported")
        await page.mouse.wheel(0, amount)
        return _ok(command, SideEffectClass.READ, f"scroll:{amount}")

    async def _upload(self, command: ActionCommand, root) -> ActionReceipt:
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        file_id = _string_value(command.value)
        if file_id is None or self._file_resolver is None:
            return _rejected(command, "file_id_unresolved")
        try:
            path = self._file_resolver.resolve(file_id)
        except Exception:
            return _rejected(command, "file_id_unknown")
        if not path.is_file():
            return _rejected(command, "file_id_missing")
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            return _rejected(command, "file_too_large")
        await locator.set_input_files(str(path), timeout=ACTION_TIMEOUT_MS)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._evidence.record_action(
            {"operation": "upload", "target": command.target.intent, "file_id": file_id, "media_type": media_type}
        )
        return _ok(command, SideEffectClass.REVERSIBLE, f"upload:{file_id}")

    async def _wait(self, command: ActionCommand, root) -> ActionReceipt:
        if command.target is None:
            seconds = _int_value(command.value)
            delay = seconds if seconds is not None else 0.5
            await asyncio.sleep(max(0.0, float(delay)))
            return _ok(command, SideEffectClass.READ, "wait:elapsed")
        locator = await self._single_locator(command, root)
        if isinstance(locator, ActionReceipt):
            return locator
        await locator.first.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        return _ok(command, SideEffectClass.READ, "wait:visible")

    async def _single_locator(self, command: ActionCommand, root) -> Locator | ActionReceipt:
        if command.target is None:
            return _rejected(command, "target_missing")
        locator = build_locator(root, command.target)
        if locator is None:
            return _rejected(command, "locator_unbuildable")
        count = await locator.count()
        if count == 0:
            return _rejected(command, "locator_missing")
        if count > 1:
            return _rejected(command, "locator_ambiguous")
        return locator

    def _resolve_secret(self, command: ActionCommand, credential_ref: str) -> SensitiveValue | None:
        if self._secret_resolver is None:
            return None
        grant_ref = command.secret_grant_refs[0] if command.secret_grant_refs else credential_ref
        return self._secret_resolver.resolve(grant_ref)

    def _watch_downloads(self, context_key: str, page: Page) -> None:
        if id(page) in self._watched_pages:
            return
        self._watched_pages.add(id(page))

        def record(download) -> None:
            self._pending_downloads.setdefault(context_key, []).append(download)

        page.on("download", record)

    def _store(self, command: ActionCommand, receipt: ActionReceipt) -> ActionReceipt:
        self._receipts[command.command_id] = receipt
        return receipt


def _context_key_for(command: ActionCommand) -> str:
    return str(command.run_id)


def _string_value(value: object) -> str | None:
    if isinstance(value, LiteralValue) and isinstance(value.value, str):
        return value.value
    return None


def _int_value(value: object) -> int | None:
    if isinstance(value, LiteralValue) and isinstance(value.value, int) and not isinstance(value.value, bool):
        return value.value
    if isinstance(value, LiteralValue) and isinstance(value.value, float):
        return int(value.value)
    return None


def _ok(command: ActionCommand, side_effect: SideEffectClass, ref: str) -> ActionReceipt:
    return _receipt(
        command_id=command.command_id,
        outcome=ActionOutcome.SUCCEEDED,
        side_effect=side_effect,
        observed_target=command.target,
        evidence_refs=[ref],
    )


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
