from __future__ import annotations

from agentqa.platform.statistics.missingness import check_price_basis, dedupe_repetitions, denominator


def test_empty_denominator_is_not_applicable() -> None:
    result = denominator([])
    assert result.not_applicable is True
    assert result.reason == "empty_denominator"
    assert result.n == 0


def test_non_empty_denominator_counts_missing() -> None:
    result = denominator([1, 2, 3], missing=1)
    assert result.not_applicable is False
    assert result.n == 3
    assert result.missing == 1


def test_price_basis_mismatch_is_flagged() -> None:
    report = check_price_basis(
        [
            {"basis": "price_estimate", "currency": "USD"},
            {"basis": "provider_reported", "currency": "USD"},
        ]
    )
    assert report.compatible is False
    assert report.reason == "mixed_price_basis"
    assert report.bases == ["price_estimate", "provider_reported"]


def test_currency_mismatch_is_flagged() -> None:
    report = check_price_basis(
        [
            {"basis": "price_estimate", "currency": "USD"},
            {"basis": "price_estimate", "currency": "VND"},
        ]
    )
    assert report.compatible is False
    assert report.reason == "mixed_currency"


def test_compatible_basis_passes() -> None:
    report = check_price_basis([{"basis": "price_estimate", "currency": "USD"}] * 3)
    assert report.compatible is True
    assert report.reason is None


def test_duplicate_repetitions_are_counted_not_summed() -> None:
    rows = [
        {"case": "a", "arm": "llm", "rep": 1, "value": 1.0},
        {"case": "a", "arm": "llm", "rep": 1, "value": 1.0},
        {"case": "a", "arm": "llm", "rep": 2, "value": 2.0},
    ]
    unique, duplicates = dedupe_repetitions(rows, key_fields=("case", "arm", "rep"))
    assert len(unique) == 2
    assert duplicates == 1
    assert sum(row["value"] for row in unique) == 3.0
