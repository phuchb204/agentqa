from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from agentqa.contracts.errors import ErrorCode


class SecurityError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SecretLeakError(SecurityError):
    def __init__(self, message: str = "Giá trị nhạy cảm xuất hiện ở sink không an toàn") -> None:
        super().__init__(ErrorCode.SECRET_SERIALIZATION, message)


class TaintRegistry:
    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str) -> None:
        if value:
            self._values.add(value)

    def unregister(self, value: str) -> None:
        self._values.discard(value)

    @property
    def values(self) -> frozenset[str]:
        return frozenset(self._values)

    def find(self, payload: object) -> list[str]:
        found: list[str] = []
        for value in self._values:
            if self._contains(payload, value):
                found.append(value)
        return found

    def assert_clean(self, payload: object, sink: str = "unspecified") -> None:
        found = self.find(payload)
        if found:
            raise SecretLeakError(f"Canary bị chặn tại sink '{sink}'")

    def _contains(self, payload: object, value: str) -> bool:
        if payload is None:
            return False
        if isinstance(payload, str):
            return value in payload
        if isinstance(payload, bytes):
            return value.encode("utf-8") in payload
        if isinstance(payload, Mapping):
            return any(self._contains(key, value) or self._contains(item, value) for key, item in payload.items())
        if isinstance(payload, (list, tuple, set, frozenset)):
            return any(self._contains(item, value) for item in payload)
        if isinstance(payload, BaseException):
            return self._contains(str(payload), value) or self._contains(repr(payload), value)
        return value in repr(payload)


TAINT_REGISTRY = TaintRegistry()


def scan_all(payloads: Sequence[object], registry: TaintRegistry, sink: str) -> None:
    for payload in payloads:
        registry.assert_clean(payload, sink)


def register_synthetic(registry: TaintRegistry, values: Iterable[str]) -> None:
    for value in values:
        registry.register(value)
