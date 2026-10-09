from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentqa.platform.api.application import api
from agentqa.platform.api.schemas import (
    OPENAPI_PATH,
    PUBLIC_SCHEMAS,
    build_catalog,
    canonical_json_text,
    schema_json_text,
)


def build_artifacts() -> dict[str, str]:
    artifacts = {path: schema_json_text(name, version) for (name, version), (path, _) in PUBLIC_SCHEMAS.items()}
    artifacts[OPENAPI_PATH] = canonical_json_text(api.openapi())
    artifacts["schemas/catalog.json"] = canonical_json_text(build_catalog(artifacts))
    return artifacts


def check(artifacts: dict[str, str], root: Path) -> list[str]:
    stale: list[str] = []
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            stale.append(relative)
    return stale


def write(artifacts: dict[str, str], root: Path) -> list[str]:
    written: list[str] = []
    for relative, text in artifacts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(relative)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_schemas", description="Generate or check public schemas and OpenAPI")
    parser.add_argument("--check", action="store_true", help="read-only: fail when generated output is stale")
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not (root / "pyproject.toml").is_file():
        print(f"[ERROR] {root} does not look like the repository root")
        return 2
    artifacts = build_artifacts()
    if args.check:
        stale = check(artifacts, root)
        if stale:
            for relative in stale:
                print(f"[STALE] {relative}")
            print(f"STALE: {len(stale)}")
            return 1
        print(f"CHECK OK: {len(artifacts)} artifacts up to date")
        return 0
    written = write(artifacts, root)
    for relative in written:
        print(f"[WROTE] {relative}")
    print(f"WROTE: {len(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
