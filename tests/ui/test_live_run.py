from __future__ import annotations

CHECK_NAMES = {
    "live-verdict-not-final",
    "keyboard-focus-live",
    "control-requested",
    "control-effective",
    "browser-stream-typed",
    "browser-frame-masked",
}


def _checks_by_name(report) -> dict:
    return {check.name: check for check in report.checks}


def test_live_run_verdict_controls_and_stream(live_report) -> None:
    assert live_report.ok, live_report.as_dict()
    checks = _checks_by_name(live_report)
    missing = CHECK_NAMES - set(checks)
    assert not missing, sorted(missing)
    assert checks["control-effective"].detail
