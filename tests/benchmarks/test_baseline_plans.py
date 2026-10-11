from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from agentqa.agent.replay import validate_case
from agentqa.contracts.compiler import compile_case_document

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = REPO_ROOT / "benchmarks" / "public"
INDEX_PATH = PUBLIC_ROOT / "baselines" / "index.yaml"
RUN_MARKERS = ("run_id", "source_run_id", "agent_best", "best_run", "auto_author")


def load_index() -> dict:
    return yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))


def case_files() -> set[str]:
    found: set[str] = set()
    for path in sorted((PUBLIC_ROOT / "cases").rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("schema_version") == "case/1":
            found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_index_covers_every_case_exactly_once() -> None:
    index = load_index()
    assert index["schema_version"] == "baselines/1"
    entries = index["case_baselines"]
    listed = [entry["case"] for entry in entries]
    assert len(listed) == len(set(listed))
    assert set(listed) == case_files()


def test_baseline_plans_compile_and_pass_runtime_capability() -> None:
    index = load_index()
    for entry in index["case_baselines"]:
        plan_path = REPO_ROOT / entry["plan"]
        text = plan_path.read_text(encoding="utf-8")
        compiled = compile_case_document(text)
        assert compiled.case.logical_key.endswith("_static")
        capability = validate_case(compiled.case)
        assert capability.supported, f"{entry['plan']} thiếu capability: {capability.reasons}"
        case_text = (REPO_ROOT / entry["case"]).read_text(encoding="utf-8")
        assert text != case_text, f"{entry['plan']} không được copy nguyên case"
        for marker in RUN_MARKERS:
            assert marker not in text, f"{entry['plan']} chứa marker phụ thuộc run: {marker}"


def test_baseline_digests_and_provenance_match_index() -> None:
    index = load_index()
    for entry in index["case_baselines"]:
        plan_path = REPO_ROOT / entry["plan"]
        digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        assert digest == entry["plan_sha256"], f"{entry['plan']} digest không khớp index"
        assert entry["provenance"] == "manual_authoring"
        assert int(entry["version"]) == 1


def test_baseline_plan_shares_requirement_with_case() -> None:
    index = load_index()
    for entry in index["case_baselines"]:
        case = compile_case_document((REPO_ROOT / entry["case"]).read_text(encoding="utf-8")).case
        plan = compile_case_document((REPO_ROOT / entry["plan"]).read_text(encoding="utf-8")).case
        assert set(plan.requirements) & set(case.requirements), entry["plan"]
        assert plan.fixture_refs == case.fixture_refs


def test_visual_baselines_exist_with_matching_digests() -> None:
    index = load_index()
    visual = index.get("visual_baselines", [])
    assert {entry["ref"] for entry in visual} >= {"canvasdesk_default_light", "canvasdesk_default_dark"}
    for entry in visual:
        path = REPO_ROOT / entry["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
