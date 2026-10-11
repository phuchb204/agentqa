from __future__ import annotations

import re
import sys
from pathlib import Path

SCAN_SCHEMA_VERSION = "redaction-scan/1"

SUSPICIOUS_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/=]{16,}['\"]?"
    ),
    re.compile(r"sk-(live|test|proj)-[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-+/=]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
ALLOWED_FILE_PARTS = ("redaction_scan.py", "redacted", "example", ".example", "fixture", "canary")
MAX_SCAN_BYTES = 10 * 1024 * 1024


def _targets(repo_root: Path) -> list[Path]:
    roots = [repo_root / "artifacts", repo_root / "docs", repo_root / "benchmarks"]
    targets: list[Path] = []
    for base in roots:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                targets.append(path)
    return targets


def run_redaction_scan(*, repo_root: Path) -> dict:
    findings: list[dict] = []
    scanned = 0
    for path in _targets(repo_root):
        name = path.name.lower()
        if any(part in name for part in ALLOWED_FILE_PARTS):
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        scanned += 1
        text = payload[:MAX_SCAN_BYTES].decode("utf-8", errors="ignore")
        for pattern in SUSPICIOUS_PATTERNS:
            if pattern.search(text):
                findings.append({"path": path.relative_to(repo_root).as_posix(), "pattern": pattern.pattern[:40]})
    explicit = {
        ".env": (repo_root / ".env").is_file(),
        "artifacts_contain_env": (repo_root / "artifacts" / ".env").is_file(),
    }
    return {
        "schema_version": SCAN_SCHEMA_VERSION,
        "tool": "redaction_scan",
        "ok": not findings,
        "scanned_files": scanned,
        "findings": findings[:50],
        "explicit_env_present": explicit,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="redaction_scan", description="Quét secrets trong artifacts/docs/benchmarks.")
    parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    result = run_redaction_scan(repo_root=repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
