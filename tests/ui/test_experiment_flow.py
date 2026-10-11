from __future__ import annotations

from tools.ui_harness.runner import run_scenario


def test_experiment_flow_end_to_end() -> None:
    report = run_scenario(scenario="experiments", build_web=False)
    assert report.ok, report.error
    names = {check.name for check in report.checks}
    assert {
        "experiment-execute",
        "experiments-list",
        "arm-summary-separated",
        "confound-flags",
        "slot-filter",
        "slot-drilldown",
        "experiment-charts",
    } <= names
