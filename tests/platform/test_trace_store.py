import json
from pathlib import Path

from agentqa.contracts import RunMetrics, RunTrace, RunVersions
from agentqa.platform.trace_store import write_trace


def test_write_trace_creates_json_file(tmp_path: Path):
    trace = RunTrace(
        run_id="login_todo-20260917-abc123",
        case_name="login_todo",
        status="passed",
        started_at="2026-09-17T00:00:00+00:00",
        finished_at="2026-09-17T00:00:02+00:00",
        metrics=RunMetrics(llm_calls=6, input_tokens=60, output_tokens=30, duration_s=2.0),
        versions=RunVersions(app="0.1.0", model="fake", prompt="v1"),
    )
    path = write_trace(trace, tmp_path)
    assert path == tmp_path / "login_todo-20260917-abc123" / "trace.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "passed"
    assert data["metrics"]["llm_calls"] == 6
