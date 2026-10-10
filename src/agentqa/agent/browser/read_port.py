from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.async_api import Page

from agentqa.agent.browser.action_registry import build_locator
from agentqa.agent.browser.capture import SafeEvidenceService
from agentqa.agent.browser.contexts import ContextRegistry
from agentqa.agent.browser.journals import DownloadJournal, DownloadRecord, NetworkJournal, NetworkRecord
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
MAX_NETWORK_EXCERPT = 2048
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
    def __init__(
        self,
        contexts: ContextRegistry,
        evidence: SafeEvidenceService,
        network: NetworkJournal | None = None,
        downloads: DownloadJournal | None = None,
    ) -> None:
        self._contexts = contexts
        self._evidence = evidence
        self._network = network or NetworkJournal()
        self._downloads = downloads or DownloadJournal()
        self._download_metadata: dict[str, list[dict[str, str]]] = {}
        self._wired_pages: set[int] = set()

    async def observe(self, context_key: str, mode: Modality = Modality.SEMANTIC) -> Observation:
        if mode not in (Modality.SEMANTIC, Modality.HYBRID):
            raise CapabilityUnavailableObservation(f"mode '{mode.value}' chưa được implement")
        lane = self._contexts.lane(context_key)
        page = await self._contexts.page(context_key)
        self._wire_page(context_key, page)
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
        root = await self._contexts.locator_root(context_key)
        try:
            satisfied = await self._evaluate_condition(root, page, condition)
        except ConditionUnsupported as exc:
            return ProbeOutcome(satisfied=False, error_code=exc.code)
        return ProbeOutcome(satisfied=satisfied)

    async def read_download_metadata(self, context_key: str) -> dict[str, str]:
        records = self._downloads.entries(context_key)
        if records:
            latest = records[-1]
            return {"suggested_filename": latest.filename, "sha256": latest.sha256 or ""}
        downloads = self._download_metadata.get(context_key, [])
        if not downloads:
            return {}
        latest = downloads[-1]
        return {
            "suggested_filename": latest.get("suggested_filename", ""),
            "url": latest.get("url", ""),
        }

    def download_records(self, context_key: str) -> list[DownloadRecord]:
        return self._downloads.entries(context_key)

    def network_records(self, context_key: str) -> list[NetworkRecord]:
        return self._network.entries(context_key)

    async def screenshot_png(self, context_key: str) -> bytes:
        page = await self._contexts.page(context_key)
        return await page.screenshot(type="png", full_page=False)

    async def capture_safe_evidence(self, context_key: str, label: str) -> str:
        page = await self._contexts.page(context_key)
        png = await page.screenshot(full_page=True)
        return self._evidence.emit_image(label, png, [])

    async def _evaluate_condition(self, root, page: Page, condition: Condition) -> bool:
        if isinstance(condition, AndCondition):
            for child in condition.conditions:
                if not await self._evaluate_condition(root, page, child):
                    return False
            return True
        if isinstance(condition, OrCondition):
            for child in condition.conditions:
                if await self._evaluate_condition(root, page, child):
                    return True
            return False
        if isinstance(condition, NotCondition):
            return not await self._evaluate_condition(root, page, condition.condition)
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
        locator = build_locator(root, condition.target) if condition.target is not None else None
        if comparator in ("exists", "unique", "visible", "hidden", "count_equals", "count_greater_or_equal"):
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
            visible = count > 0 and await locator.first.is_visible()
            if comparator == "hidden":
                return not visible
            visible_expected = bool(expected) if expected is not None else True
            return visible == visible_expected
        if comparator in ("text_equals", "equals", "contains", "not_equals", "text_matches"):
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
            if comparator == "text_matches":
                import re

                return re.search(expected, text) is not None
            return text == expected
        if comparator == "attribute_equals":
            if locator is None or condition.target is None or not condition.target.attributes:
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            attribute, attribute_expected = next(iter(condition.target.attributes.items()))
            value = await locator.first.get_attribute(attribute)
            return value == (attribute_expected if expected is None else expected)
        if comparator in ("value_equals", "state_checked", "state_enabled"):
            if locator is None:
                raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)
            count = await locator.count()
            if count != 1:
                raise ConditionUnsupported(ErrorCode.LOCATOR_AMBIGUOUS if count > 1 else ErrorCode.LOCATOR_MISSING)
            if comparator == "value_equals":
                value = await locator.first.input_value()
                return value == (expected if isinstance(expected, str) else "")
            if comparator == "state_checked":
                checked = await locator.first.is_checked()
                return checked == (bool(expected) if expected is not None else True)
            enabled = await locator.first.is_enabled()
            return enabled == (bool(expected) if expected is not None else True)
        raise ConditionUnsupported(ErrorCode.CAPABILITY_UNAVAILABLE)

    def _wire_page(self, context_key: str, page: Page) -> None:
        if id(page) in self._wired_pages:
            return
        self._wired_pages.add(id(page))

        def record(download) -> None:
            self._download_metadata.setdefault(context_key, []).append(
                {"suggested_filename": download.suggested_filename, "url": download.url}
            )

        def record_response(response) -> None:
            try:
                request = response.request
                if request.resource_type not in ("xhr", "fetch", "document"):
                    return
                body_digest = None
                body_excerpt = None
                try:
                    body = response.body()
                except Exception:
                    body = None
                if body:
                    body_digest = sha256(body).hexdigest()
                    content_type = (response.headers or {}).get("content-type", "")
                    if "json" in content_type and len(body) <= MAX_NETWORK_EXCERPT * 4:
                        excerpt = body.decode("utf-8", errors="replace")[:MAX_NETWORK_EXCERPT]
                        body_excerpt = self._evidence.sanitize_text(excerpt)
                self._network.record(
                    context_key,
                    NetworkRecord(
                        method=request.method,
                        url=self._evidence.sanitize_url(response.url),
                        status=response.status,
                        body_digest=body_digest,
                        body_excerpt=body_excerpt,
                    ),
                )
            except Exception:
                return

        page.on("download", record)
        page.on("response", record_response)


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
