from __future__ import annotations


def test_keyboard_focus_flow(live_report) -> None:
    assert live_report.ok, live_report.as_dict()
    checks = {check.name: check for check in live_report.checks}
    assert "keyboard-focus-live" in checks
    assert checks["keyboard-focus-live"].ok
