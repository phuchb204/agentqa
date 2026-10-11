from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tools.acceptance.catalog import build_catalog, check_kind
from tools.acceptance.runner import CheckOutcome, run_catalog


class FakeExecutor:
    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls = 0

    def run(self, catalog) -> dict[str, CheckOutcome]:
        self.calls += 1
        outcomes: dict[str, CheckOutcome] = {}
        for check in catalog.checks:
            status = self.overrides.get(check.id, "passed")
            outcomes[check.id] = CheckOutcome(
                check_id=check.id,
                kind=check_kind(check),
                status=status,
                detail="fake executor",
                duration_s=0.0,
            )
        return outcomes


def _report_payload(tmp_path: Path, executor: FakeExecutor) -> dict:
    catalog = build_catalog()
    report = run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=executor)
    payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    return payload


def test_full_pass_report_ok(tmp_path: Path) -> None:
    executor = FakeExecutor()
    catalog = build_catalog()
    report = run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=executor)
    assert executor.calls == 1
    assert report.ok is True
    assert all(outcome.status == "passed" for outcome in report.scenarios)
    assert (tmp_path / "latest.json").is_file()
    payload = report.as_dict()
    assert payload["schema_version"] == "acceptance-report/1"
    assert payload["filtered"] is False
    for item in payload["scenarios"]:
        assert item["business_effect"]
        assert item["proof"]
        assert item["denominator"]


def test_failed_check_fails_scenario_and_run(tmp_path: Path) -> None:
    executor = FakeExecutor({"pytest.ac01.author_replay": "failed"})
    catalog = build_catalog()
    report = run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=executor)
    assert report.ok is False
    failure = next(outcome for outcome in report.scenarios if outcome.scenario.id == "AC-01")
    assert failure.status == "failed"
    assert failure.scenario.check_ids[0] == "pytest.ac01.author_replay"


def test_not_run_check_never_passes(tmp_path: Path) -> None:
    executor = FakeExecutor({"pytest.ac08.healing": "not_run"})
    catalog = build_catalog()
    report = run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=executor)
    assert report.ok is False
    target = next(outcome for outcome in report.scenarios if outcome.scenario.id == "AC-08")
    assert target.status == "not_run"
    assert "latest.json" in [path.name for path in tmp_path.iterdir()]


def test_missing_executor_outcome_is_not_run(tmp_path: Path) -> None:
    class IncompleteExecutor(FakeExecutor):
        def run(self, catalog) -> dict[str, CheckOutcome]:
            outcomes = super().run(catalog)
            outcomes.pop("pytest.ac01.author_replay")
            return outcomes

    catalog = build_catalog()
    report = run_catalog(catalog, repo_root=tmp_path, report_dir=tmp_path, executor=IncompleteExecutor())
    assert report.ok is False
    assert report.checks["pytest.ac01.author_replay"].status == "not_run"
    assert next(o for o in report.scenarios if o.scenario.id == "AC-01").status == "not_run"


def test_catalog_gap_blocks_execution(tmp_path: Path) -> None:
    catalog = build_catalog()
    trimmed = dataclasses.replace(catalog, scenarios=tuple(s for s in catalog.scenarios if s.id != "AC-24"))
    executor = FakeExecutor()
    report = run_catalog(trimmed, repo_root=tmp_path, report_dir=tmp_path, executor=executor)
    assert executor.calls == 0
    assert report.ok is False
    assert any("AC-24" in gap for gap in report.gaps)
    assert not (tmp_path / "latest.json").exists()


def test_filtered_run_does_not_write_latest(tmp_path: Path) -> None:
    catalog = build_catalog()
    report = run_catalog(
        catalog,
        repo_root=tmp_path,
        report_dir=tmp_path,
        executor=FakeExecutor(),
        scenario_ids=("AC-01",),
    )
    assert report.filtered is True
    assert report.ok is True
    assert not (tmp_path / "latest.json").exists()
    assert [outcome.scenario.id for outcome in report.scenarios] == ["AC-01"]


def test_filtered_unknown_scenario_gap(tmp_path: Path) -> None:
    catalog = build_catalog()
    report = run_catalog(
        catalog,
        repo_root=tmp_path,
        report_dir=tmp_path,
        executor=FakeExecutor(),
        scenario_ids=("AC-77",),
    )
    assert report.ok is False
    assert any("AC-77" in gap for gap in report.gaps)


def test_report_payload_roundtrip(tmp_path: Path) -> None:
    payload = _report_payload(tmp_path, FakeExecutor())
    assert payload["ok"] is True
    assert len(payload["scenarios"]) == 36
    assert payload["scenarios"][0]["id"] == "AC-01"
    assert payload["scenarios"][-1]["id"] == "NFR-12"
