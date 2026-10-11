from __future__ import annotations

import pytest

from agentqa.platform.statistics.samples import (
    conservative_zero_event_units,
    sample_size_from_conservative_bound,
    sample_size_from_pilot,
    sample_size_from_pilot_rows,
)


def test_conservative_zero_event_units_known_vector() -> None:
    assert conservative_zero_event_units(0.01, confidence=0.95) == 299
    assert conservative_zero_event_units(0.05, confidence=0.95) == 59
    assert conservative_zero_event_units(0.01, confidence=0.99) == 459


def test_conservative_report_documents_assumptions() -> None:
    report = sample_size_from_conservative_bound(0.01, confidence=0.95)
    assert report.units == 299
    assert report.method == "conservative_zero_event_bound"
    assert report.target_rate == 0.01
    assert "zero observed errors" in report.assumptions["rule"]
    assert report.algorithm_version == "samples/1"


def test_pilot_variance_known_vector() -> None:
    report = sample_size_from_pilot(0.1, precision=0.05, confidence=0.95)
    assert report.units == 139
    assert report.assumptions["precision"] == 0.05
    assert report.assumptions["pilot_rate"] == 0.1


def test_pilot_rows_report_uses_mean_and_digest() -> None:
    report = sample_size_from_pilot_rows([0.0, 0.1, 0.2], precision=0.05)
    assert report.assumptions["pilot_units"] == 3
    assert report.assumptions["pilot_rate"] == pytest.approx(0.1)
    assert report.pilot_digest is not None and len(report.pilot_digest) == 64


def test_sample_size_requires_predeclared_inputs() -> None:
    with pytest.raises(ValueError):
        sample_size_from_pilot(0.1, precision=0.0)
    with pytest.raises(ValueError):
        conservative_zero_event_units(0.0)
    with pytest.raises(ValueError):
        sample_size_from_pilot_rows([], precision=0.05)
