from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentqa.platform.security.taint import TaintRegistry

REDACTED = "[REDACTED]"


class RedactionService:
    def __init__(self, registry: TaintRegistry, placeholder: str = REDACTED) -> None:
        self._registry = registry
        self._placeholder = placeholder

    def register(self, value: str) -> None:
        self._registry.register(value)

    def redact_text(self, text: str) -> str:
        redacted = text
        for value in self._registry.values:
            redacted = redacted.replace(value, self._placeholder)
        return redacted

    def redact_structure(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, bytes):
            return self.redact_text(value.decode("utf-8", errors="replace")).encode("utf-8")
        if isinstance(value, Mapping):
            return {self.redact_text(str(key)): self.redact_structure(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact_structure(item) for item in value]
        if isinstance(value, BaseException):
            return self.redact_text(str(value))
        return self.redact_text(repr(value))

    def safe_error_message(self, error: BaseException) -> str:
        return self.redact_text(str(error))
