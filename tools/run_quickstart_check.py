from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

COPY_DIRS = ("src", "tests", "tools", "schemas", "benchmarks", "apps", "docs", "infra", ".github")
COPY_FILES = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    ".python-version",
    ".npmrc",
    ".gitignore",
    ".gitattributes",
    "README.md",
    "AGENTS.md",
    "LICENSE",
)
IGNORE_NAMES = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _copy_fresh(root: Path, target: Path) -> None:
    for name in COPY_DIRS:
        source = root / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
    for name in COPY_FILES:
        source = root / name
        if source.is_file():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / name)


def _run(command: list[str], cwd: Path, lines: list[str]) -> int:
    lines.append(f"$ {' '.join(command)}")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            check=False,
            shell=sys.platform == "win32",
        )
    except subprocess.TimeoutExpired:
        lines.append("timeout 3600s")
        return 124
    tail = (completed.stdout or "") + (completed.stderr or "")
    lines.extend(tail.strip().splitlines()[-400:])
    lines.append(f"exit={completed.returncode}")
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="run_quickstart_check", description="Fresh install từ bản sạch + gates offline."
    )
    parser.parse_args(argv)

    temp_root = Path(tempfile.mkdtemp(prefix="agentqa-quickstart-"))
    lines: list[str] = [f"fresh copy: {temp_root}"]
    _copy_fresh(REPO_ROOT, temp_root)
    steps: list[dict] = []

    def record(name: str, code: int) -> None:
        steps.append({"name": name, "exit": code, "ok": code == 0})
        if code != 0:
            raise SystemExit(code)

    try:
        record("uv-sync", _run(["uv", "sync", "--locked"], temp_root, lines))
        record("ruff-check", _run(["uv", "run", "--locked", "ruff", "check", "."], temp_root, lines))
        record(
            "ruff-format",
            _run(["uv", "run", "--locked", "ruff", "format", "--check", "."], temp_root, lines),
        )
        record("lint-imports", _run(["uv", "run", "--locked", "lint-imports"], temp_root, lines))
        record(
            "export-schemas",
            _run(["uv", "run", "--locked", "python", "tools/export_schemas.py", "--check"], temp_root, lines),
        )
        record(
            "plan-coverage",
            _run(["uv", "run", "--locked", "python", "tools/check_plan_coverage.py"], temp_root, lines),
        )
        record(
            "pytest-offline",
            _run(
                [
                    "uv",
                    "run",
                    "--locked",
                    "pytest",
                    "-q",
                    "tests/contracts",
                    "tests/foundation",
                    "tests/acceptance",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                ],
                temp_root,
                lines,
            ),
        )
        record("pnpm-install", _run(["pnpm", "--dir", "apps/web", "install", "--frozen-lockfile"], temp_root, lines))
        record("web-typecheck", _run(["pnpm", "--dir", "apps/web", "typecheck"], temp_root, lines))
        record("web-test", _run(["pnpm", "--dir", "apps/web", "test"], temp_root, lines))
        record("web-build", _run(["pnpm", "--dir", "apps/web", "build"], temp_root, lines))
    except SystemExit as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "steps": steps,
                    "lines": lines[-200:],
                    "temp": str(temp_root),
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return int(error.code or 1)
    print(
        json.dumps(
            {
                "ok": True,
                "steps": steps,
                "lines": lines[-200:],
                "temp": str(temp_root),
                "generated_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
