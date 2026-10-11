from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from agentqa.agent.browser.action_registry import build_locator
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.verification import (
    AssertionSpec,
    Comparator,
    EvidenceStatus,
    NetworkFilter,
)
from agentqa.verify.evaluators import DownloadEntry, NetworkEntry

TEXT_COMPARATORS = frozenset(
    {
        Comparator.EQUALS,
        Comparator.TEXT_EQUALS,
        Comparator.CONTAINS,
        Comparator.NOT_EQUALS,
        Comparator.TEXT_MATCHES,
    }
)


@dataclass
class FactsSnapshot:
    url_value: str = "about:blank"
    counts: dict[str, int] = field(default_factory=dict)
    texts: dict[str, str | None] = field(default_factory=dict)
    visibles: dict[str, bool] = field(default_factory=dict)
    hiddens: dict[str, bool] = field(default_factory=dict)
    values: dict[str, str | None] = field(default_factory=dict)
    checkeds: dict[str, bool | None] = field(default_factory=dict)
    enableds: dict[str, bool | None] = field(default_factory=dict)
    attributes: dict[tuple[str, str], str | None] = field(default_factory=dict)
    evidence: dict[str, EvidenceStatus] = field(default_factory=dict)
    captures: dict[str, object] = field(default_factory=dict)
    parameters: dict[str, object] = field(default_factory=dict)
    network_entries: list[NetworkEntry] = field(default_factory=list)
    download_entries: list[DownloadEntry] = field(default_factory=list)
    baseline_bytes: dict[str, bytes] = field(default_factory=dict)
    screenshot_bytes: bytes | None = None

    def url(self) -> str:
        return self.url_value

    def count(self, target: TargetDescriptor) -> int:
        return self.counts.get(target.intent, 0)

    def text(self, target: TargetDescriptor) -> str | None:
        return self.texts.get(target.intent)

    def value(self, target: TargetDescriptor) -> str | None:
        return self.values.get(target.intent, self.texts.get(target.intent))

    def visible(self, target: TargetDescriptor) -> bool:
        return self.visibles.get(target.intent, False)

    def hidden(self, target: TargetDescriptor) -> bool:
        if target.intent in self.hiddens:
            return self.hiddens[target.intent]
        return self.count(target) > 0 and not self.visible(target)

    def attribute(self, target: TargetDescriptor, name: str) -> str | None:
        return self.attributes.get((target.intent, name))

    def checked(self, target: TargetDescriptor) -> bool | None:
        return self.checkeds.get(target.intent)

    def enabled(self, target: TargetDescriptor) -> bool | None:
        return self.enableds.get(target.intent)

    def evidence_status(self, assertion_id: str) -> EvidenceStatus:
        return self.evidence.get(assertion_id, EvidenceStatus.PRESENT)

    def capture(self, name: str) -> object | None:
        return self.captures.get(name)

    def parameter(self, name: str) -> object | None:
        return self.parameters.get(name)

    def network(self, filter: NetworkFilter) -> list[NetworkEntry]:
        matched: list[NetworkEntry] = []
        for entry in self.network_entries:
            if filter.method and entry.method.upper() != filter.method.upper():
                continue
            if filter.path_contains and filter.path_contains not in urlsplit(entry.url).path:
                continue
            if filter.status is not None and entry.status != filter.status:
                continue
            if filter.body_contains and (entry.body_excerpt is None or filter.body_contains not in entry.body_excerpt):
                continue
            matched.append(entry)
        return matched

    def downloads(self) -> list[DownloadEntry]:
        return list(self.download_entries)

    def baseline(self, ref: str) -> bytes | None:
        return self.baseline_bytes.get(ref)

    def screenshot(self) -> bytes | None:
        return self.screenshot_bytes


async def capture_facts(
    contexts: ContextRegistry,
    context_key: str,
    assertions: list[AssertionSpec],
    evidence: dict[str, EvidenceStatus] | None = None,
    overrides: dict[str, TargetDescriptor] | None = None,
    *,
    captures: dict[str, object] | None = None,
    parameters: dict[str, object] | None = None,
    read_port=None,
    baseline_resolver=None,
) -> FactsSnapshot:
    page = await contexts.page(context_key)
    root = await contexts.locator_root(context_key)
    snapshot = FactsSnapshot(
        url_value=page.url,
        evidence=dict(evidence or {}),
        captures=dict(captures or {}),
        parameters=dict(parameters or {}),
    )
    for assertion in assertions:
        target = (overrides or {}).get(assertion.id, assertion.target)
        if target is None:
            continue
        locator = build_locator(root, target)
        if locator is None:
            continue
        count = await locator.count()
        snapshot.counts[target.intent] = count
        if assertion.comparator in TEXT_COMPARATORS:
            snapshot.texts[target.intent] = (await locator.first.inner_text()).strip() if count == 1 else None
        if assertion.comparator in (Comparator.VISIBLE, Comparator.HIDDEN):
            snapshot.visibles[target.intent] = count > 0 and await locator.first.is_visible()
        if assertion.comparator == Comparator.VALUE_EQUALS:
            snapshot.values[target.intent] = (await locator.first.input_value()) if count == 1 else None
        if assertion.comparator == Comparator.STATE_CHECKED:
            snapshot.checkeds[target.intent] = (await locator.first.is_checked()) if count == 1 else None
        if assertion.comparator == Comparator.STATE_ENABLED:
            snapshot.enableds[target.intent] = (await locator.first.is_enabled()) if count == 1 else None
        if assertion.comparator == Comparator.ATTRIBUTE_EQUALS:
            for name in target.attributes:
                snapshot.attributes[(target.intent, name)] = (
                    await locator.first.get_attribute(name) if count >= 1 else None
                )
    if read_port is not None:
        snapshot.network_entries = [
            NetworkEntry(
                method=record.method,
                url=record.url,
                status=record.status,
                body_digest=record.body_digest,
                body_excerpt=record.body_excerpt,
            )
            for record in read_port.network_records(context_key)
        ]
        snapshot.download_entries = [
            DownloadEntry(
                filename=record.filename,
                media_type=record.media_type,
                size_bytes=record.size_bytes,
                sha256=record.sha256,
            )
            for record in read_port.download_records(context_key)
        ]
        wants_visual = any(assertion.comparator == Comparator.VISUAL_MATCH for assertion in assertions)
        if wants_visual:
            try:
                snapshot.screenshot_bytes = await read_port.screenshot_png(context_key)
            except Exception:
                snapshot.screenshot_bytes = None
    if baseline_resolver is not None:
        for assertion in assertions:
            if assertion.visual is not None and assertion.visual.baseline_ref not in snapshot.baseline_bytes:
                data = baseline_resolver(assertion.visual.baseline_ref)
                if data is not None:
                    snapshot.baseline_bytes[assertion.visual.baseline_ref] = data
    return snapshot


def origin_of_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


BASELINE_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?$")


class DirectoryBaselineResolver:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def __call__(self, ref: str) -> bytes | None:
        if not BASELINE_REF_PATTERN.match(ref):
            return None
        candidate = (self._root / f"{ref}.png").resolve()
        if not candidate.is_relative_to(self._root) or not candidate.is_file():
            return None
        return candidate.read_bytes()
