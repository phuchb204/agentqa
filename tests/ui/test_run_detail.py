from __future__ import annotations


def test_run_detail_shows_server_verdict_and_usage(live_report) -> None:
    assert live_report.ok, live_report.as_dict()
    names = {check.name for check in live_report.checks}
    assert "run-detail-verdict" in names
    assert "strict-run-passed" in names
