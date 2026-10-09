from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FR_IDS = [f"FR-{index:02d}" for index in range(1, 52)]
NFR_IDS = [f"NFR-{index:02d}" for index in range(1, 13)]
AC_IDS = [f"AC-{index:02d}" for index in range(1, 25)]
TASK_IDS = [f"P{index:02d}" for index in range(1, 33)]

ROW_RE = re.compile(r"^\|\s*((?:FR|NFR|AC)-\d{2})\s*\|", re.MULTILINE)
ID_RE = re.compile(r"\b(?:FR|NFR|AC)-\d{2}\b")
TASK_ROW_RE = re.compile(r"^\|\s*(P\d{2})\s*\|\s*([^|]*)\|", re.MULTILINE)
TASK_REF_RE = re.compile(r"\bP\d{2}\b")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")


class Gaps:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, code: str, detail: str) -> None:
        self.items.append(f"[GAP] {code} {detail}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_definitions(spec_text: str, gaps: Gaps) -> None:
    expected = set(FR_IDS) | set(NFR_IDS) | set(AC_IDS)
    seen: list[str] = []
    for match in ROW_RE.finditer(spec_text):
        ident = match.group(1)
        seen.append(ident)
    duplicates = sorted({ident for ident in seen if seen.count(ident) > 1})
    missing = sorted(expected - set(seen))
    unknown = sorted(set(seen) - expected)
    for ident in missing:
        gaps.add("SPEC_ID_MISSING", f"{ident} has no definition row in product-spec.md")
    for ident in duplicates:
        gaps.add("SPEC_ID_DUPLICATE", f"{ident} has multiple definition rows in product-spec.md")
    for ident in unknown:
        gaps.add("SPEC_ID_UNKNOWN", f"{ident} is outside FR-01..FR-51/NFR-01..NFR-12/AC-01..AC-24")


def check_mappings(plan_text: str, gaps: Gaps) -> dict[str, list[str]]:
    expected = set(FR_IDS) | set(NFR_IDS) | set(AC_IDS)
    mappings: dict[str, list[str]] = {}
    for match in ROW_RE.finditer(plan_text):
        ident = match.group(1)
        if ident in mappings:
            gaps.add("PLAN_ID_DUPLICATE", f"{ident} has multiple mapping rows in acceptance-plan.md")
            continue
        line_start = plan_text.rfind("\n", 0, match.end()) + 1
        line_end = plan_text.find("\n", match.end())
        row = plan_text[line_start:line_end]
        refs = sorted(set(TASK_REF_RE.findall(row)) - {ident})
        mappings[ident] = refs
        for ref in refs:
            if ref not in TASK_IDS:
                gaps.add("PLAN_TASK_UNKNOWN", f"{ident} references unknown task {ref}")
    for ident in sorted(expected - set(mappings)):
        gaps.add("PLAN_ID_MISSING", f"{ident} has no mapping row in acceptance-plan.md")
    for ident in sorted(set(mappings) - expected):
        gaps.add("PLAN_ID_UNKNOWN", f"{ident} mapping is outside the spec ID space")
    return mappings


def check_task_graph(plan_text: str, gaps: Gaps) -> None:
    tasks: dict[str, list[str]] = {}
    for match in TASK_ROW_RE.finditer(plan_text):
        task_id = match.group(1)
        raw_depends = match.group(2).strip()
        if task_id in tasks:
            gaps.add("TASK_DUPLICATE", f"{task_id} has multiple definition rows in rebuild-plan.md")
            continue
        depends = [] if raw_depends in {"", "—", "-"} else sorted(set(TASK_REF_RE.findall(raw_depends)))
        tasks[task_id] = depends
    for task_id in TASK_IDS:
        if task_id not in tasks:
            gaps.add("TASK_MISSING", f"{task_id} has no definition row in rebuild-plan.md")
    for task_id, depends in tasks.items():
        for ref in depends:
            if ref not in TASK_IDS:
                gaps.add("TASK_DEP_UNKNOWN", f"{task_id} depends on unknown task {ref}")
            elif ref not in tasks:
                gaps.add("TASK_DEP_MISSING", f"{task_id} depends on undefined task {ref}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join([*stack, node])
            gaps.add("TASK_CYCLE", f"dependency cycle: {cycle}")
            return
        visiting.add(node)
        for ref in tasks.get(node, []):
            if ref in tasks:
                visit(ref, [*stack, node])
        visiting.discard(node)
        visited.add(node)

    for task_id in tasks:
        visit(task_id, [])


def check_links(docs_root: Path, gaps: Gaps) -> None:
    for markdown in sorted(docs_root.rglob("*.md")):
        text = read_text(markdown)
        for target in LINK_RE.findall(text):
            cleaned = target.strip()
            if not cleaned or cleaned.startswith(EXTERNAL_PREFIXES) or "://" in cleaned:
                continue
            path_part = cleaned.split("#", 1)[0]
            if not path_part or path_part.startswith("/"):
                continue
            resolved = (markdown.parent / path_part).resolve()
            if not resolved.exists():
                gaps.add("LINK_BROKEN", f"{markdown.as_posix()} -> {cleaned}")


def run(docs_root: Path) -> Gaps:
    gaps = Gaps()
    spec_text = read_text(docs_root / "specs" / "product-spec.md")
    acceptance_plan = read_text(docs_root / "plans" / "acceptance-plan.md")
    rebuild_plan = read_text(docs_root / "plans" / "rebuild-plan.md")
    check_definitions(spec_text, gaps)
    mappings = check_mappings(acceptance_plan, gaps)
    used = set(TASK_REF_RE.findall(acceptance_plan)) | {ref for refs in mappings.values() for ref in refs}
    for task_id in TASK_IDS:
        if task_id not in used:
            gaps.add("TASK_UNUSED", f"{task_id} is not referenced in acceptance-plan.md")
    check_task_graph(rebuild_plan, gaps)
    check_links(docs_root, gaps)
    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_plan_coverage", description="Validate spec/design/plan coverage")
    parser.add_argument("--docs-root", default="docs", help="Docs directory to validate")
    args = parser.parse_args(argv)
    docs_root = Path(args.docs_root)
    if not docs_root.is_dir():
        print(f"[GAP] DOCS_ROOT_MISSING {docs_root} is not a directory")
        return 2
    gaps = run(docs_root)
    if gaps.items:
        for item in sorted(gaps.items):
            print(item)
        print(f"GAPS: {len(gaps.items)}")
        return 1
    print("CHECK OK: FR-01..FR-51, NFR-01..NFR-12, AC-01..AC-24 mapped; P01..P32 DAG valid; links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
