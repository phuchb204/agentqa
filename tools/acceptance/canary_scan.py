from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

SCAN_SCHEMA_VERSION = "canary-scan/1"
SCAN_ROOTS = (
    "artifacts/acceptance",
    "artifacts/faults",
    "artifacts/ui-e2e",
    "artifacts/workloads",
    "artifacts/demo",
    "artifacts/release",
    "artifacts/os-smoke",
    "artifacts/web-tests",
)
KNOWN_CANARIES = (
    "agentqa-ui-canary-key-7f21",
    "canary-synthetic-4b91d0",
    "canary-credential-value-7f3a",
    "canary-anchor-4d1e7a",
    "canary-credential-9f3b2c",
    "artifact-canary-8830",
    "synthetic-provider-key-canary",
    "sk-canary-secret-do-not-log",
)
CANARY_PATTERN = re.compile(r"(?i)canary[-_][A-Za-z0-9._-]*\d[A-Za-z0-9._-]*")
EXCLUDED_FILE_NAMES = frozenset({"canary-scan.json", "canary_scan.py"})
MAX_SCAN_BYTES = 20 * 1024 * 1024


def _iter_targets(repo_root: Path) -> list[Path]:
    targets: list[Path] = []
    for root in SCAN_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                targets.append(path)
    return targets


def run_canary_scan(*, repo_root: Path, run_dir: Path | None = None) -> dict:
    matches: list[dict] = []
    scanned = 0
    for path in _iter_targets(repo_root):
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        scanned += 1
        text = payload[:MAX_SCAN_BYTES].decode("utf-8", errors="ignore")
        relative = path.relative_to(repo_root).as_posix()
        for literal in KNOWN_CANARIES:
            if literal in text:
                matches.append({"path": relative, "kind": "literal", "value": literal})
        for found in CANARY_PATTERN.finditer(text):
            value = found.group(0)
            if any(value == literal or value in literal or literal in value for literal in KNOWN_CANARIES):
                continue
            matches.append({"path": relative, "kind": "pattern", "value": value})
    return {
        "schema_version": SCAN_SCHEMA_VERSION,
        "tool": "canary-scan",
        "ok": not matches,
        "scanned_files": scanned,
        "matches": matches[:100],
        "matches_total": len(matches),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="canary-scan", description="Quét synthetic canary trên safe sinks trong artifacts."
    )
    parser.add_argument("--report-dir", default="artifacts/acceptance", help="thư mục ghi kết quả scan")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    result = run_canary_scan(repo_root=repo_root)
    report_dir = repo_root / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "canary-scan.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
