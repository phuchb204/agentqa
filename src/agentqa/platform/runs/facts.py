from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agentqa.agent.browser.action_registry import build_locator
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.verification import AssertionSpec, Comparator, EvidenceStatus

TEXT_COMPARATORS = frozenset(
    {
        Comparator.EQUALS,
        Comparator.TEXT_EQUALS,
        Comparator.CONTAINS,
        Comparator.NOT_EQUALS,
    }
)


@dataclass
class FactsSnapshot:
    url_value: str = "about:blank"
    counts: dict[str, int] = field(default_factory=dict)
    texts: dict[str, str | None] = field(default_factory=dict)
    visibles: dict[str, bool] = field(default_factory=dict)
    attributes: dict[tuple[str, str], str | None] = field(default_factory=dict)
    evidence: dict[str, EvidenceStatus] = field(default_factory=dict)

    def url(self) -> str:
        return self.url_value

    def count(self, target: TargetDescriptor) -> int:
        return self.counts.get(target.intent, 0)

    def text(self, target: TargetDescriptor) -> str | None:
        return self.texts.get(target.intent)

    def value(self, target: TargetDescriptor) -> str | None:
        return self.texts.get(target.intent)

    def visible(self, target: TargetDescriptor) -> bool:
        return self.visibles.get(target.intent, False)

    def attribute(self, target: TargetDescriptor, name: str) -> str | None:
        return self.attributes.get((target.intent, name))

    def evidence_status(self, assertion_id: str) -> EvidenceStatus:
        return self.evidence.get(assertion_id, EvidenceStatus.PRESENT)


async def capture_facts(
    contexts: ContextRegistry,
    context_key: str,
    assertions: list[AssertionSpec],
    evidence: dict[str, EvidenceStatus] | None = None,
) -> FactsSnapshot:
    page = await contexts.page(context_key)
    snapshot = FactsSnapshot(url_value=page.url, evidence=dict(evidence or {}))
    for assertion in assertions:
        target = assertion.target
        if target is None:
            continue
        locator = build_locator(page, target)
        if locator is None:
            continue
        count = await locator.count()
        snapshot.counts[target.intent] = count
        if assertion.comparator in TEXT_COMPARATORS:
            snapshot.texts[target.intent] = (await locator.first.inner_text()).strip() if count == 1 else None
        if assertion.comparator == Comparator.VISIBLE:
            snapshot.visibles[target.intent] = count > 0 and await locator.first.is_visible()
        if assertion.comparator == Comparator.ATTRIBUTE_EQUALS:
            for name in target.attributes:
                snapshot.attributes[(target.intent, name)] = (
                    await locator.first.get_attribute(name) if count >= 1 else None
                )
    return snapshot


def origin_of_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"
