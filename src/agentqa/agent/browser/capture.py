from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageDraw

REDACTED = "[REDACTED]"
SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key"})
SENSITIVE_QUERY_HINTS = ("token", "secret", "password", "key", "code", "session")


class TextRedactor(Protocol):
    def redact_text(self, text: str) -> str: ...

    def redact_structure(self, value: Any) -> Any: ...


class EvidenceSink(Protocol):
    def put(self, label: str, payload: bytes, media_type: str) -> str: ...


class TaintSource(Protocol):
    @property
    def values(self) -> frozenset[str]: ...


@dataclass(frozen=True)
class MaskRegion:
    x: int
    y: int
    width: int
    height: int

    def clamp(self, size: tuple[int, int]) -> MaskRegion:
        max_width, max_height = size
        x = max(0, min(self.x, max_width))
        y = max(0, min(self.y, max_height))
        width = max(0, min(self.width, max_width - x))
        height = max(0, min(self.height, max_height - y))
        return MaskRegion(x=x, y=y, width=width, height=height)


class SafeEvidenceService:
    def __init__(
        self,
        redactor: TextRedactor,
        sink: EvidenceSink,
        taint: TaintSource | None = None,
    ) -> None:
        self._redactor = redactor
        self._sink = sink
        self._taint = taint
        self._history: list[dict[str, Any]] = []

    @property
    def history(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._history)

    def register_secret(self, value: str) -> None:
        register = getattr(self._redactor, "register", None)
        if callable(register):
            register(value)

    def sanitize_semantic(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        sanitized = self._redactor.redact_structure(dict(snapshot))
        for candidate in sanitized.get("candidates", []):
            if isinstance(candidate, dict) and candidate.get("input_type") == "password":
                candidate["name"] = REDACTED
        return sanitized

    def sanitize_network(self, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for record in records:
            entry = dict(record)
            headers = entry.get("headers")
            if isinstance(headers, Mapping):
                entry["headers"] = {
                    name: (REDACTED if name.lower() in SENSITIVE_HEADERS else self._redactor.redact_text(str(value)))
                    for name, value in headers.items()
                }
            url = entry.get("url")
            if isinstance(url, str):
                entry["url"] = self.sanitize_url(url)
            sanitized.append(entry)
        return sanitized

    def sanitize_url(self, url: str) -> str:
        parts = urlsplit(url)
        query = []
        for name, value in parse_qsl(parts.query, keep_blank_values=True):
            if name.lower() in SENSITIVE_QUERY_HINTS or self._is_tainted(value):
                query.append((name, REDACTED))
            else:
                query.append((name, self._redactor.redact_text(value)))
        userinfo = ""
        if parts.username or parts.password:
            userinfo = REDACTED + "@"
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, userinfo + host, parts.path, urlencode(query), parts.fragment))

    def mask_image(self, png_bytes: bytes, regions: Iterable[MaskRegion]) -> bytes:
        with Image.open(io.BytesIO(png_bytes)) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        for region in regions:
            bounded = region.clamp(image.size)
            if bounded.width and bounded.height:
                draw.rectangle(
                    [bounded.x, bounded.y, bounded.x + bounded.width, bounded.y + bounded.height],
                    fill=(0, 0, 0),
                )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def emit_semantic(self, label: str, snapshot: Mapping[str, Any]) -> str:
        sanitized = self.sanitize_semantic(snapshot)
        self.assert_sink_clean(sanitized)
        return self._sink.put(label, _to_json_bytes(sanitized), "application/json")

    def emit_image(self, label: str, png_bytes: bytes, regions: Iterable[MaskRegion]) -> str:
        masked = self.mask_image(png_bytes, regions)
        self.assert_sink_clean(masked)
        return self._sink.put(label, masked, "image/png")

    def record_action(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        recorded = self._redactor.redact_structure(dict(entry))
        if self._taint is not None:
            recorded["taint_labels"] = sorted(
                name for name in ("secret", "capture", "url") if _contains_taint(entry, self._taint.values)
            )
        self._history.append(recorded)
        return recorded

    def assert_sink_clean(self, payload: object) -> None:
        if self._taint is None:
            return
        for value in self._taint.values:
            if _contains(payload, value):
                raise ValueError("sensitive value xuất hiện trước sink an toàn")

    def _is_tainted(self, value: str) -> bool:
        if self._taint is None:
            return False
        return any(secret in value for secret in self._taint.values)


def _to_json_bytes(value: object) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _contains(payload: object, value: str) -> bool:
    if payload is None:
        return False
    if isinstance(payload, str):
        return value in payload
    if isinstance(payload, bytes):
        return value.encode("utf-8") in payload
    if isinstance(payload, Mapping):
        return any(_contains(key, value) or _contains(item, value) for key, item in payload.items())
    if isinstance(payload, (list, tuple, set, frozenset)):
        return any(_contains(item, value) for item in payload)
    return value in repr(payload)


def _contains_taint(payload: object, values: frozenset[str]) -> bool:
    return any(_contains(payload, value) for value in values)
