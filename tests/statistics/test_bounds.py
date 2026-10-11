from __future__ import annotations

import math

import pytest

from agentqa.platform.statistics.bounds import exact_lower_bound, exact_one_sided, exact_upper_bound
from agentqa.platform.statistics.grouping import cluster_bootstrap


def test_zero_event_upper_bound_matches_closed_form() -> None:
    for units in (10, 100, 299):
        expected = 1.0 - (1.0 - 0.95) ** (1.0 / units)
        actual = exact_upper_bound(0, units, confidence=0.95)
        assert actual is not None
        assert actual == pytest.approx(expected, abs=1e-12)
        assert actual > 0.0


def test_known_vector_nonzero_errors() -> None:
    upper = exact_upper_bound(1, 50, confidence=0.95)
    lower = exact_lower_bound(1, 50, confidence=0.95)
    assert upper == pytest.approx(0.09139813071969738, abs=1e-12)
    assert lower == pytest.approx(0.0010253398672320645, abs=1e-12)
    assert lower < 1 / 50 < upper


def test_one_sided_result_shape_and_zero_event_flag() -> None:
    result = exact_one_sided(0, 100, confidence=0.95)
    assert result.zero_event is True
    assert result.method == "clopper_pearson_one_sided"
    assert result.lower == 0.0
    assert result.upper is not None and result.upper > 0.0


def test_bootstrap_all_zero_is_not_reported_as_zero_upper_bound() -> None:
    degenerate = cluster_bootstrap({"only-family": [0.0, 0.0, 0.0]}, seed=7)
    assert degenerate.sufficient_support is False
    assert degenerate.upper is None
    assert degenerate.reason == "insufficient_support"
    exact = exact_upper_bound(0, 3, confidence=0.95)
    assert exact is not None and exact > 0.0


def test_bounds_validation() -> None:
    with pytest.raises(ValueError):
        exact_upper_bound(3, 2)
    with pytest.raises(ValueError):
        exact_upper_bound(0, 10, confidence=1.0)
    assert exact_upper_bound(0, 0) is None


def test_floor_between_lower_and_upper() -> None:
    for errors, units in ((0, 20), (2, 20), (5, 20), (20, 20)):
        lower = exact_lower_bound(errors, units, confidence=0.9)
        upper = exact_upper_bound(errors, units, confidence=0.9)
        assert lower is not None and upper is not None
        assert 0.0 <= lower <= upper <= 1.0
        assert lower <= errors / units <= upper


def test_binomial_reference_value_against_manual_sum() -> None:
    # P(X <= 1 | n=50, p=0.09) <= 0.05 < P(X <= 1 | n=50, p=0.0914)
    def cdf(p: float, k: int = 1, n: int = 50) -> float:
        return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))

    upper = exact_upper_bound(1, 50, confidence=0.95)
    assert upper is not None
    assert cdf(upper) == pytest.approx(0.05, abs=1e-6)
