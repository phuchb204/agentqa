from pathlib import Path

from agentqa.contracts import (
    AssertionResult,
    AssertionSpec,
    MutationSpec,
    RunMetrics,
    RunTrace,
    RunVersions,
    load_case,
)


def test_run_trace_defaults_are_serializable():
    trace = RunTrace(
        run_id="r1",
        case_name="login",
        status="failed",
        started_at="2026-09-17T00:00:00+00:00",
        finished_at="2026-09-17T00:00:01+00:00",
        metrics=RunMetrics(),
        versions=RunVersions(app="0.1.0", model="fake", prompt="v1"),
    )
    assert trace.steps == []
    assert trace.assertions == []
    assert trace.error == ""
    assert '"r1"' in trace.model_dump_json()


def test_assertion_result_status_is_checked():
    result = AssertionResult(assertion_id="a1", status="passed", detail="ok")
    assert result.status == "passed"


def test_mutation_spec_holds_ground_truth():
    spec = MutationSpec(id="m1", variant="id-change", ground_truth="Add button still works")
    assert spec.changes == []
    assert spec.ground_truth.startswith("Add")


def test_load_case_from_yaml(tmp_path: Path):
    case_file = tmp_path / "case.yaml"
    case_file.write_text(
        "name: login\n"
        "start_path: login.html\n"
        'goal: "Đăng nhập và thêm việc"\n'
        "max_steps: 15\n"
        "assertions:\n"
        "  - id: a1\n"
        "    kind: text_visible\n"
        '    value: "Mua sữa"\n',
        encoding="utf-8",
    )
    case = load_case(case_file)
    assert case.name == "login"
    assert case.max_steps == 15
    assert case.assertions == [AssertionSpec(id="a1", kind="text_visible", value="Mua sữa")]


def test_load_case_rejects_missing_fields(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\n", encoding="utf-8")
    try:
        load_case(bad)
        raise AssertionError("expected validation error")
    except ValueError:
        pass
