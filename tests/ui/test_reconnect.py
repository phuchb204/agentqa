from __future__ import annotations


def test_reconnect_dedupes_and_stale_token_closes_access(live_report) -> None:
    assert live_report.ok, live_report.as_dict()
    names = {check.name for check in live_report.checks}
    assert "reconnect-dedupe" in names
    assert "stale-token-acl" in names
    assert "tab-close-engine-continues" in names
