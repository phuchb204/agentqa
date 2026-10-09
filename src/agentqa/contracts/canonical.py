from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal
from hashlib import sha256
from typing import Any

import rfc8785
from pydantic import BaseModel

from agentqa.contracts.values import ensure_safe_json

CONTENT_DOMAIN = b"agentqa/content/1"
SNAPSHOT_DOMAIN = b"agentqa/run-snapshot/1"


class FrozenMapping(Mapping[str, Any]):
    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("FrozenMapping is immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("FrozenMapping is immutable")

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("FrozenMapping is immutable")


def to_portable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {key: to_portable(item) for key, item in value.model_dump().items()}
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): to_portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_portable(item) for item in value]
    return value


def canonicalize(value: Any) -> bytes:
    portable = to_portable(value)
    ensure_safe_json(portable)
    return rfc8785.dumps(portable)


def digest_content(document: Any) -> str:
    return sha256(CONTENT_DOMAIN + b"\x00" + canonicalize(document)).hexdigest()


def digest_run_snapshot(snapshot: Any) -> str:
    return sha256(SNAPSHOT_DOMAIN + b"\x00" + canonicalize(snapshot)).hexdigest()


def digest_artifact_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def freeze(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return freeze(value.model_dump())
    if isinstance(value, Mapping):
        return FrozenMapping({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value
