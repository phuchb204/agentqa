from __future__ import annotations


def test_compare_shows_config_diff_before_metrics(live_report) -> None:
    assert live_report.ok, live_report.as_dict()
    names = {check.name for check in live_report.checks}
    assert "compare-config-first" in names
