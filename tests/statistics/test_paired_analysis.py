from __future__ import annotations

from agentqa.platform.statistics.paired import DEFAULT_REPLICATES, paired_bootstrap


def test_paired_bootstrap_estimate_and_ci() -> None:
    result = paired_bootstrap(
        {
            "taskboard": [(10.0, 5.0), (8.0, 6.0)],
            "shopflow": [(4.0, 4.0), (6.0, 3.0)],
        },
        seed=20261010,
        replicates=3000,
    )
    assert result.sufficient_support is True
    assert result.estimate == 2.5
    assert result.strata == 2
    assert result.pairs == 4
    assert result.lower is not None and result.upper is not None
    assert result.lower <= result.estimate <= result.upper
    assert result.seed == 20261010
    assert result.replicates == 3000


def test_paired_bootstrap_is_seed_reproducible() -> None:
    strata = {"taskboard": [(1.0, 0.0), (2.0, 1.0)], "shopflow": [(3.0, 1.0)]}
    first = paired_bootstrap(strata, seed=42, replicates=1000)
    second = paired_bootstrap(strata, seed=42, replicates=1000)
    assert first == second


def test_default_replicates_pinned_at_ten_thousand() -> None:
    assert DEFAULT_REPLICATES == 10_000


def test_paired_bootstrap_insufficient_without_pairs() -> None:
    result = paired_bootstrap({}, seed=1)
    assert result.sufficient_support is False
    assert result.reason == "insufficient_support"
    assert result.estimate is None


def test_paired_bootstrap_stratifies_by_application() -> None:
    strata = {
        "a": [(1.0, 0.0)] * 10,
        "b": [(100.0, 99.0)] * 10,
    }
    result = paired_bootstrap(strata, seed=5, replicates=2000)
    assert result.strata == 2
    assert result.pairs == 20
    assert result.estimate == 1.0
