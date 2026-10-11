from __future__ import annotations

from agentqa.platform.statistics.grouping import cluster_bootstrap
from agentqa.platform.statistics.multiple import holm_adjust


def test_cluster_bootstrap_same_seed_same_result() -> None:
    data = {"a": [1.0, 0.0], "b": [0.0, 0.0], "c": [1.0, 1.0]}
    first = cluster_bootstrap(data, seed=99, replicates=1500)
    second = cluster_bootstrap(data, seed=99, replicates=1500)
    assert first == second
    assert first.seed == 99
    assert first.replicates == 1500


def test_cluster_bootstrap_records_pinned_seed() -> None:
    result = cluster_bootstrap({"a": [0.0], "b": [1.0]}, replicates=100)
    assert result.seed == 20261010
    assert result.replicates == 100


def test_holm_adjustment_known_vector() -> None:
    result = holm_adjust(["h1", "h2", "h3", "h4", "h5"], [0.01, 0.02, 0.03, 0.04, 0.05], alpha=0.05)
    assert result.adjusted == [0.05, 0.08, 0.09, 0.09, 0.09]
    assert result.rejected == [True, False, False, False, False]
    assert result.labels[0] == "h1"


def test_holm_keeps_family_adjustment_monotonic() -> None:
    result = holm_adjust(["a", "b", "c"], [0.001, 0.2, 0.5], alpha=0.05)
    assert result.adjusted[0] <= result.adjusted[1] <= result.adjusted[2]
    assert result.rejected[0] is True
    assert result.rejected[1] is False


def test_holm_rejects_mismatched_lengths() -> None:
    import pytest

    with pytest.raises(ValueError):
        holm_adjust(["a"], [0.1, 0.2])
