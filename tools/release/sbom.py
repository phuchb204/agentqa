from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

SBOM_SCHEMA_VERSION = "sbom/1"


def _sha256(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _parse_uv_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    components: list[dict[str, str]] = []
    for package in data.get("package", []):
        name = str(package.get("name", "")).strip()
        version = str(package.get("version", "")).strip()
        if name and version:
            components.append({"ecosystem": "pypi", "name": name, "version": version})
    return components


def _parse_pnpm_lock(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    components: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in data.get("packages") or {}:
        text = str(key).strip()
        if text.startswith("/"):
            text = text[1:]
        if "@" not in text:
            continue
        if text.startswith("@"):
            scope, _, rest = text[1:].partition("/")
            name_part, _, version = rest.rpartition("@")
            name = f"@{scope}/{name_part}" if name_part else ""
        else:
            name, _, version = text.rpartition("@")
        version = version.split("(", 1)[0].strip()
        if not name or not version or version.startswith("link:"):
            continue
        identity = f"{name}@{version}"
        if identity in seen:
            continue
        seen.add(identity)
        components.append({"ecosystem": "npm", "name": name, "version": version})
    return components


def build_sbom(repo_root: Path) -> dict[str, Any]:
    uv_components = _parse_uv_lock(repo_root / "uv.lock")
    npm_components = _parse_pnpm_lock(repo_root / "pnpm-lock.yaml")
    return {
        "schema_version": SBOM_SCHEMA_VERSION,
        "tool": "build_sbom",
        "sources": {
            "uv_lock": _sha256(repo_root / "uv.lock"),
            "pnpm_lock": _sha256(repo_root / "pnpm-lock.yaml"),
        },
        "counts": {"pypi": len(uv_components), "npm": len(npm_components)},
        "components": sorted(
            [*uv_components, *npm_components],
            key=lambda item: (item["ecosystem"], item["name"], item["version"]),
        ),
    }
