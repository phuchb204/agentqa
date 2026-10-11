from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PRIVATE_ROOT = REPO_ROOT / "benchmarks" / "private"
if str(PRIVATE_ROOT) not in sys.path:
    sys.path.insert(0, str(PRIVATE_ROOT))

from agentqa.contracts.canonical import digest_content  # noqa: E402
from agentqa.contracts.compiler import compile_case_document  # noqa: E402
from agentqa.contracts.errors import AgentQAValidationError  # noqa: E402
from agentqa.platform.fixtures import (  # noqa: E402
    CANVASDESK_FIXTURE,
    SHOPFLOW_FIXTURE,
    TASKBOARD_FIXTURE,
    FixtureDefinition,
)

CASES_ROOT = Path("benchmarks/public/cases")
DATA_ROOT = Path("benchmarks/public/data")
FIXTURES_ROOT = Path("benchmarks/public/fixtures")
REQUIREMENTS_ROOT = Path("benchmarks/public/requirements")
BASELINES_ROOT = Path("benchmarks/public/baselines")
INVENTORY_PATH = Path("benchmarks/public/inventory.yaml")

OPERATION_GROUPS = {
    "navigate": "navigate",
    "fill": "form_input",
    "type": "form_input",
    "clear": "form_input",
    "press": "form_input",
    "click": "pointer",
    "double_click": "pointer",
    "hover": "pointer",
    "check": "selection",
    "uncheck": "selection",
    "select": "selection",
    "scroll": "scroll",
    "upload": "upload_download",
    "expect_download": "upload_download",
    "switch_frame": "frame_tab",
    "switch_page": "frame_tab",
    "wait": "wait",
    "handle_dialog": "dialog",
}

COMPARATOR_GROUPS = {
    "exists": "presence",
    "absent": "presence",
    "visible": "presence",
    "hidden": "presence",
    "equals": "text_value",
    "not_equals": "text_value",
    "contains": "text_value",
    "text_equals": "text_value",
    "text_matches": "text_value",
    "value_equals": "text_value",
    "attribute_equals": "attributes_state",
    "state_checked": "attributes_state",
    "state_enabled": "attributes_state",
    "count_equals": "counts",
    "count_greater_or_equal": "counts",
    "unique": "counts",
    "url_equals": "url",
    "url_path_equals": "url",
    "network_request": "network",
    "download_matches": "download",
    "visual_match": "visual",
}

KNOWN_FIXTURES: dict[str, FixtureDefinition] = {
    definition.fixture_id: definition for definition in (TASKBOARD_FIXTURE, SHOPFLOW_FIXTURE, CANVASDESK_FIXTURE)
}


class Gaps:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, code: str, detail: str) -> None:
        self.items.append(f"[GAP] {code} {detail}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def walk_nodes(nodes: list[Any]) -> list[Any]:
    collected: list[Any] = []
    for node in nodes:
        collected.append(node)
        if getattr(node, "kind", None) == "branch":
            collected.extend(walk_nodes(list(node.then_nodes)))
            collected.extend(walk_nodes(list(node.else_nodes)))
        elif getattr(node, "kind", None) == "loop":
            collected.extend(walk_nodes(list(node.body)))
    return collected


def derive_groups(case) -> tuple[set[str], set[str]]:
    action_groups: set[str] = set()
    evaluator_groups: set[str] = set()
    for node in walk_nodes(list(case.nodes)):
        if node.kind == "action":
            group = OPERATION_GROUPS.get(node.operation.value)
            if group is not None:
                action_groups.add(group)
        if node.kind == "checkpoint":
            for assertion in node.assertions:
                group = COMPARATOR_GROUPS.get(assertion.comparator.value)
                if group is not None:
                    evaluator_groups.add(group)
    return action_groups, evaluator_groups


def check_source_anchors(case, root: Path, gaps: Gaps, case_path: str) -> None:
    sources: dict[str, Path] = {}
    for candidate in list((root / REQUIREMENTS_ROOT).glob("*.md")) + list((root / CASES_ROOT).glob("*/source.md")):
        sources.setdefault(sha256_bytes(candidate.read_bytes()), candidate)
    for name, ref in case.source_defs.items():
        source = sources.get(ref.source_content_digest)
        if source is None:
            gaps.add("SOURCE_MISSING", f"{case_path} source_defs.{name} digest không khớp file nguồn nào")
            continue
        text = source.read_text(encoding="utf-8")
        section = f"## {ref.anchor.value}"
        index = text.find(section)
        if index < 0:
            gaps.add("ANCHOR_MISSING", f"{case_path} source_defs.{name} không thấy anchor '{section}' trong {source}")
            continue
        body = text[index + len(section) :].lstrip("\n")
        paragraph = body.split("\n\n", 1)[0].strip()
        if sha256_bytes(paragraph.encode("utf-8")) != ref.quote_digest:
            gaps.add("QUOTE_MISMATCH", f"{case_path} source_defs.{name} quote_digest không khớp đoạn văn nguồn")


def check_fixtures(case, root: Path, gaps: Gaps, case_path: str) -> None:
    for fixture_ref in case.fixture_refs:
        fixture_id, _, version = fixture_ref.partition("@")
        recipe_path = root / FIXTURES_ROOT / f"{fixture_id}.yaml"
        if not recipe_path.is_file():
            gaps.add("FIXTURE_RECIPE_MISSING", f"{case_path} thiếu recipe benchmarks/public/fixtures/{fixture_id}.yaml")
            continue
        recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        if str(recipe.get("version")) != version:
            gaps.add(
                "FIXTURE_VERSION_MISMATCH",
                f"{case_path} dùng {fixture_ref} nhưng recipe version {recipe.get('version')}",
            )
            continue
        definition = KNOWN_FIXTURES.get(fixture_id)
        if definition is None:
            gaps.add("FIXTURE_DEFINITION_MISSING", f"{case_path} fixture '{fixture_id}' không có definition runtime")
            continue
        if recipe.get("seeds") != definition.seeds:
            gaps.add(
                "FIXTURE_RECIPE_DRIFT",
                f"benchmarks/public/fixtures/{fixture_id}.yaml khác FixtureDefinition runtime",
            )
        if definition.default_seed not in definition.seeds:
            gaps.add("FIXTURE_DEFAULT_SEED", f"fixture '{fixture_id}' default_seed không có trong seeds")


def load_baseline_index(root: Path, gaps: Gaps) -> dict[str, Any]:
    path = root / BASELINES_ROOT / "index.yaml"
    if not path.is_file():
        gaps.add("BASELINE_INDEX_MISSING", "benchmarks/public/baselines/index.yaml không tồn tại")
        return {"case_baselines": [], "visual_baselines": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check_baselines(root: Path, case_rel: str, case, index: dict[str, Any], gaps: Gaps) -> None:
    entries = [entry for entry in index.get("case_baselines", []) if entry.get("case") == case_rel]
    if len(entries) != 1:
        gaps.add("BASELINE_ENTRY", f"{case_rel} cần đúng một baseline entry, thấy {len(entries)}")
        return
    entry = entries[0]
    plan_path = root / entry["plan"]
    if not plan_path.is_file():
        gaps.add("BASELINE_PLAN_MISSING", f"{case_rel} thiếu plan {entry['plan']}")
        return
    if sha256_bytes(plan_path.read_bytes()) != entry.get("plan_sha256"):
        gaps.add("BASELINE_DIGEST", f"{case_rel} plan sha256 không khớp index")
    if entry.get("provenance") != "manual_authoring":
        gaps.add("BASELINE_PROVENANCE", f"{case_rel} baseline provenance phải là manual_authoring")
    text = plan_path.read_text(encoding="utf-8")
    for marker in ("run_id", "source_run_id", "agent_best", "auto_author"):
        if marker in text:
            gaps.add("BASELINE_NOT_INDEPENDENT", f"{case_rel} baseline chứa marker '{marker}'")
    try:
        plan = compile_case_document(text).case
    except AgentQAValidationError as exc:
        gaps.add("BASELINE_INVALID", f"{case_rel} baseline không compile được: {exc.errors[:1]}")
        return
    if not (set(plan.requirements) & set(case.requirements)):
        gaps.add("BASELINE_REQUIREMENT", f"{case_rel} baseline không chia sẻ requirement với case")


def check_visual_refs(case, index: dict[str, Any], root: Path, gaps: Gaps, case_path: str) -> None:
    visual_entries = {entry["ref"]: entry for entry in index.get("visual_baselines", [])}
    for node in walk_nodes(list(case.nodes)):
        if node.kind != "checkpoint":
            continue
        for assertion in node.assertions:
            if assertion.visual is None:
                continue
            entry = visual_entries.get(assertion.visual.baseline_ref)
            if entry is None:
                gaps.add(
                    "VISUAL_REF_MISSING",
                    f"{case_path} baseline_ref '{assertion.visual.baseline_ref}' không có trong index",
                )
                continue
            image_path = root / entry["path"]
            if not image_path.is_file() or sha256_bytes(image_path.read_bytes()) != entry.get("sha256"):
                gaps.add("VISUAL_DIGEST", f"{case_path} visual baseline {entry['path']} thiếu hoặc sai digest")


def check_data(root: Path, gaps: Gaps) -> None:
    for data_path in sorted((root / DATA_ROOT).glob("*.yaml")):
        document = yaml.safe_load(data_path.read_text(encoding="utf-8"))
        digest = document.get("rows_digest")
        actual = digest_content(document.get("rows", []))
        if digest != actual:
            gaps.add("DATA_DIGEST", f"{data_path.name} rows_digest không khớp nội dung rows")


def check_oracle(case_keys: set[str], gaps: Gaps) -> None:
    try:
        from oracle.registry import record_for, registry_digest
    except ImportError:
        gaps.add("ORACLE_PACKAGE", "không import được private oracle package tại benchmarks/private")
        return
    for key in sorted(case_keys):
        if record_for(key) is None:
            gaps.add("ORACLE_RECORD_MISSING", f"case '{key}' thiếu oracle record độc lập")
    if not registry_digest():
        gaps.add("ORACLE_DIGEST", "oracle registry digest rỗng")


def run(root: Path) -> tuple[Gaps, dict[str, Any]]:
    gaps = Gaps()
    inventory = yaml.safe_load((root / INVENTORY_PATH).read_text(encoding="utf-8"))
    listed: dict[str, dict[str, Any]] = {
        str(key).replace("\\", "/"): value or {} for key, value in inventory.get("cases", {}).items()
    }
    case_paths: dict[str, Path] = {}
    for path in sorted((root / CASES_ROOT).rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("schema_version") == "case/1":
            case_paths[path.relative_to(root).as_posix()] = path
    for case_rel in sorted(set(case_paths) - set(listed)):
        gaps.add("CASE_UNCLASSIFIED", f"{case_rel} chưa được phân loại trong inventory.yaml")
    for case_rel in sorted(set(listed) - set(case_paths)):
        gaps.add("CASE_UNKNOWN", f"inventory.yaml liệt kê {case_rel} nhưng không có case file")

    index = load_baseline_index(root, gaps)
    cohort_coverage: dict[str, list[str]] = {}
    error_coverage: dict[str, list[str]] = {}
    action_coverage: dict[str, list[str]] = {}
    evaluator_coverage: dict[str, list[str]] = {}
    app_coverage: dict[str, set[str]] = {}
    case_keys: set[str] = set()

    for case_rel in sorted(case_paths):
        if case_rel not in listed:
            continue
        case_path = case_paths[case_rel]
        try:
            compiled = compile_case_document(case_path.read_text(encoding="utf-8"))
        except AgentQAValidationError as exc:
            gaps.add("CASE_INVALID", f"{case_rel} không compile được: {exc.errors[:1]}")
            continue
        case = compiled.case
        case_keys.add(case.logical_key)
        entry = listed[case_rel]
        cohort = entry.get("cohort")
        cohort_coverage.setdefault(str(cohort), []).append(case_rel)
        for error_kind in entry.get("error_kinds", []) or []:
            error_coverage.setdefault(str(error_kind), []).append(case_rel)
        action_groups, evaluator_groups = derive_groups(case)
        for group in action_groups:
            action_coverage.setdefault(group, []).append(case_rel)
        for group in evaluator_groups:
            evaluator_coverage.setdefault(group, []).append(case_rel)
        app = case_rel.split("/")[3]
        app_coverage.setdefault(app, set()).update(evaluator_groups)
        check_source_anchors(case, root, gaps, case_rel)
        check_fixtures(case, root, gaps, case_rel)
        check_baselines(root, case_rel, case, index, gaps)
        check_visual_refs(case, index, root, gaps, case_rel)

    for cohort in inventory.get("required_cohorts", []):
        if not cohort_coverage.get(str(cohort)):
            gaps.add("COHORT_UNCOVERED", f"không case nào thuộc cohort '{cohort}'")
    for error_kind in inventory.get("required_error_kinds", []):
        if not error_coverage.get(str(error_kind)):
            gaps.add("ERROR_UNCOVERED", f"không case nào phủ error kind '{error_kind}'")
    for group in inventory.get("required_action_groups", []):
        if not action_coverage.get(str(group)):
            gaps.add("ACTION_UNCOVERED", f"không case nào phủ action group '{group}'")
    for group in inventory.get("required_evaluator_groups", []):
        if not evaluator_coverage.get(str(group)):
            gaps.add("EVALUATOR_UNCOVERED", f"không case nào phủ evaluator group '{group}'")
    check_data(root, gaps)
    check_oracle(case_keys, gaps)

    summary = {
        "cases": len(case_paths),
        "cohorts": {key: len(value) for key, value in sorted(cohort_coverage.items())},
        "error_kinds": {key: len(value) for key, value in sorted(error_coverage.items())},
        "action_groups": {key: len(value) for key, value in sorted(action_coverage.items())},
        "evaluator_groups": {key: len(value) for key, value in sorted(evaluator_coverage.items())},
        "apps": {key: sorted(value) for key, value in sorted(app_coverage.items())},
    }
    return gaps, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_benchmark_inventory", description="Validate corpus inventory")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--json", action="store_true", help="in summary JSON")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(args.root).resolve()
    if not (root / "benchmarks" / "public" / "inventory.yaml").is_file():
        print(f"[ERROR] {root} không phải repo root có corpus")
        return 2
    gaps, summary = run(root)
    if args.json:
        import json

        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    if gaps.items:
        for item in sorted(gaps.items):
            print(item)
        print(f"GAPS: {len(gaps.items)}")
        return 1
    print(
        "CHECK OK: "
        f"{summary['cases']} cases · cohorts {summary['cohorts']} · errors {summary['error_kinds']} · "
        f"actions {summary['action_groups']} · evaluators {summary['evaluator_groups']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
