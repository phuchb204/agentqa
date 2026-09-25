from pathlib import Path

from agentqa.contracts import RunTrace


def write_trace(trace: RunTrace, out_dir: Path) -> Path:
    run_dir = Path(out_dir) / trace.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "trace.json"
    path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    return path
