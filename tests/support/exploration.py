from __future__ import annotations

from typing import Any


class FakeSitePort:
    def __init__(self, site: dict[str, dict[str, Any]]) -> None:
        self.site = site
        self.base_url: str | None = None
        self.opened: list[str] = []
        self.snapshots: list[str] = []
        self.writes: list[str] = []

    async def open(self, base_url: str) -> None:
        self.base_url = base_url
        self.opened.append(base_url)

    async def snapshot(self, url: str) -> dict[str, Any]:
        self.snapshots.append(url)
        if url not in self.site:
            return {"title": "", "links": [], "forms": 0}
        return dict(self.site[url])

    async def attempt_write(self, url: str) -> bool:
        self.writes.append(url)
        return True


def default_site(base: str = "http://site.test/") -> dict[str, dict[str, Any]]:
    return {
        base: {
            "title": "Trang chủ",
            "links": [f"{base}a", f"{base}b", "http://evil.example/x"],
            "forms": 1,
        },
        f"{base}a": {"title": "Trang A", "links": [base], "forms": 0},
        f"{base}b": {"title": "Trang B", "links": [], "forms": 0},
    }


__all__ = ["FakeSitePort", "default_site"]
