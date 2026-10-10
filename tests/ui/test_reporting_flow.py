from __future__ import annotations

from tools.ui_harness.runner import run_scenario


def test_reporting_flow_end_to_end() -> None:
    report = run_scenario(scenario="reporting", build_web=False)
    assert report.ok, report.error
    names = {check.name for check in report.checks}
    assert {
        "report-created",
        "issue-package-preview",
        "diagnostic-label",
        "gate-rejection-labelled",
        "unknown-cost-visible",
    } <= names
