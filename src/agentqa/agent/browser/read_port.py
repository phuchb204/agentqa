from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.async_api import Page

from agentqa.agent.browser.action_registry import build_locator
from agentqa.agent.browser.capture import SafeEvidenceService
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.contracts.case import (
    AndCondition,
    CaptureCondition,
    ComparisonCondition,
    Condition,
    NotCondition,
    OrCondition,
)
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.observation import Modality, Observation, ProbeOutcome, RedactionStatus, TruncationManifest
from agentqa.contracts.values import LiteralValue

SEMANTIC_SCRIPT_VERSION = 1
MAX_CANDIDATES = 200
SEMANTIC_SCRIPT = """
() => {
  const nodes = Array.from(
    document.querySelectorAll('a,button,input,select,textarea,li,h1,h2,h3,form,[role]')
  ).slice(0, 200);
  return nodes.map((el, index) => {
    const rect = el.getBoundingClientRect();
    let name = el.getAttribute('aria-label') || el.getAttribute('name') || el.textContent || '';
    name = name.trim().slice(0, 120);
    return {
      id: 'c' + index,
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      name,
      tag: el.tagName.toLowerCase(),
      input_type: el.getAttribute('type') || '',
      box: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
    };
  });
}
"""


class PlaywrightReadPort:
    def __init__(self, contexts: ContextRegistry, evidence: SafeEvidenceService) -> None:
        self._contexts = contexts
        self._evidence = evidence
        self._downloads: dict[str, list[dict[str, str]]] = {}
        self._wired_pages: set[int] = set()

    async def observe(self, context_key: str, mode: Modality = Modality.SEMANTIC) -> Observation:
        if mode not in (Modality.SEMANTIC, Modality.HYBRID):
            raise CapabilityUnavailableObservation(f"mode '{mode.value}' chưa được implement")
        lane = self._contexts.lane(context_key)
        page = await self._contexts.page(context_key)
        self._wire_downloads(context_key, page)
        candidates = await page.evaluate(SEMANTIC_SCRIPT)
        aria = await page.locator("body").aria_snapshot()
        snapshot = {
            "url": self._evidence.sanitize_url(page.url),
            "aria": aria,
            "candidates": candidates,
        }
        ref = self._evidence.emit_semantic(f"observation-{context_key}", snapshot)
        version = lane.next_observation_version()
        payload_size = len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
        truncation = TruncationManifest(
            dropped_regions=["candidates>200"]
            if isinstance(candidates, list) and len(candidates) >= MAX_CANDIDATES
            else [],
            reason="candidate limit" if isinstance(candidates, list) and len(candidates) >= MAX_CANDIDATES else None,
        )
        return Observation(
            observation_id=uuid4(),
            version=version,
            session_key=context_key,
            page_key="main",
            observed_at=datetime.now(UTC),
            mode=Modality.SEMANTIC,
            semantic_ref=ref,
            image_ref=None,
            candidate_refs=[candidate["id"] for candidate in candidates] if isinstance(candidates, list) else [],
            size_bytes=payload_size,
            redaction=RedactionStatus.REDACTED,
            truncation=truncation,
        )

    async def probe(self, condition: Condition, context_key: str) -> ProbeOutcome:
        page = await self._contexts.page(context_key)
        try:
            satisfied = await self._evaluate_condition(page, condition)
        except ConditionUnsupported as exc:
            return ProbeOutcome(satisfied=False, error_code=exc.code)
        return ProbeOutcome(satisfied=satisfied)

    async def read_download_metadata(self, context_key: str) -> dict[str, str]:
        downloads = self._downloads.get(context_key, [])
        if not downloads:
            return {}
        latest = downloads[-1]
        return {
            "suggested_filename": latest.get("suggested_filename", ""),
            "url": latest.get("url", ""),
        }

    async def capture_safe_evidence(self, context_key: str, label: str) -> str:
        page = await self._contexts.page(context_key)
        png = await page.screenshot(full_page=True)
        return self._evidence.emit_image(label, png, [])

    async def _evaluate_condition(self, page: Page, condition: Condition) -> bool:
        if isinstance(condition, AndCondition):
            for child in condition.conditions:
                if not await self._evaluate_condition(page, child):
                    return False
            return True
        if isinstance(condition, OrCondition):
            for child in condition.conditions:
                if await self._evaluate_condition(page, child):
                    return True
            return False
        if isinstance(condition, NotCondition):
            return not await self._evaluate_condition(page, condition.condition)
        if isinstance(condition, CaptureCondition):
            raise ConditionUnsupported(ErrorCode.INVALID_CAPTURE)
        if not isinstance(condition, ComparisonCondition):
            raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
        comparator = condition.comparator.value
        expected = _literal(condition.expected)
        if comparator == "url_path_equals":
            if not isinstance(expected, str):
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            return urlsplit(page.url).path == expected
        locator = build_locator(page, condition.target) if condition.target is not None else None
        if comparator in ("exists", "unique", "visible", "count_equals", "count_greater_or_equal"):
            if locator is None:
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            count = await locator.count()
            if comparator == "exists":
                return count > 0
            if comparator == "unique":
                return count == 1
            if comparator == "count_equals":
                return isinstance(expected, int | float) and count == int(expected)
            if comparator == "count_greater_or_equal":
                return isinstance(expected, int | float) and count >= int(expected)
            visible_expected = bool(expected) if expected is not None else True
            visible = count > 0 and await locator.first.is_visible()
            return visible == visible_expected
        if comparator in ("text_equals", "equals", "contains", "not_equals"):
            if locator is None or not isinstance(expected, str):
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            count = await locator.count()
            if comparator == "not_equals":
                return count == 0 or (await locator.first.inner_text()).strip() != expected
            if count != 1:
                raise ConditionUnsupported(ErrorCode.LOCATOR_AMBIGUOUS if count > 1 else ErrorCode.LOCATOR_MISSING)
            text = (await locator.first.inner_text()).strip()
            if comparator == "contains":
                return expected in text
            return text == expected
        if comparator == "attribute_equals":
            if locator is None or condition.target is None or not condition.target.attributes:
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            attribute, attribute_expected = next(iter(condition.target.attributes.items()))
            value = await locator.first.get_attribute(attribute)
            return value == (attribute_expected if expected is None else expected)
        raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)

    def _wire_downloads(self, context_key: str, page: Page) -> None:
        if id(page) in self._wired_pages:
            return
        self._wired_pages.add(id(page))

        def record(download) -> None:
            self._downloads.setdefault(context_key, []).append(
                {"suggested_filename": download.suggested_filename, "url": download.url}
            )

        page.on("download", record)


class CapabilityUnavailableObservation(RuntimeError):
    def __init__(self, message: str) -> None:
        self.code = ErrorCode.CAPABILITY_UNAVAILABLE
        super().__init__(message)


class ConditionUnsupported(RuntimeError):
    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def _literal(value: object) -> object | None:
    if isinstance(value, LiteralValue):
        return value.value
    return None
