from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NetworkRecord:
    method: str
    url: str
    status: int
    body_digest: str | None = None
    body_excerpt: str | None = None


@dataclass(frozen=True)
class DownloadRecord:
    filename: str
    media_type: str | None
    size_bytes: int | None
    sha256: str | None
    artifact_ref: str | None = None


@dataclass
class NetworkJournal:
    _entries: dict[str, list[NetworkRecord]] = field(default_factory=dict)

    def record(self, context_key: str, entry: NetworkRecord) -> None:
        self._entries.setdefault(context_key, []).append(entry)

    def entries(self, context_key: str) -> list[NetworkRecord]:
        return list(self._entries.get(context_key, []))

    def clear(self, context_key: str) -> None:
        self._entries.pop(context_key, None)


@dataclass
class DownloadJournal:
    _entries: dict[str, list[DownloadRecord]] = field(default_factory=dict)

    def record(self, context_key: str, entry: DownloadRecord) -> None:
        self._entries.setdefault(context_key, []).append(entry)

    def entries(self, context_key: str) -> list[DownloadRecord]:
        return list(self._entries.get(context_key, []))

    def clear(self, context_key: str) -> None:
        self._entries.pop(context_key, None)
