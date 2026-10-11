from __future__ import annotations

from agentqa.platform.statistics.grouping import cluster_bootstrap


def test_grouped_estimate_matches_mean_and_reports_support() -> None:
    result = cluster_bootstrap(
        {"taskboard": [1.0, 0.0], "shopflow": [0.0, 0.0], "canvasdesk": [1.0, 1.0]},
        seed=11,
        replicates=2000,
    )
    assert result.sufficient_support is True
    assert result.estimate == 0.5
    assert result.groups == 3
    assert result.units == 6
    assert result.lower is not None and result.upper is not None
    assert result.lower <= result.estimate <= result.upper
    assert result.group_counts == {"canvasdesk": 2, "shopflow": 2, "taskboard": 2}


def test_single_group_reports_insufficient_support_with_counts() -> None:
    result = cluster_bootstrap({"only": [0.0, 1.0]}, seed=1)
    assert result.sufficient_support is False
    assert result.reason == "insufficient_support"
    assert result.group_counts == {"only": 2}
    assert result.estimate is None


def test_empty_groups_report_insufficient_support() -> None:
    result = cluster_bootstrap({}, seed=1)
    assert result.sufficient_support is False
    assert result.units == 0


def test_degenerate_cluster_bootstrap_does_not_claim_rare_event_ceiling() -> None:
    result = cluster_bootstrap({"a": [0.0], "b": [0.0]}, seed=3, replicates=500)
    assert result.sufficient_support is True
    assert result.estimate == 0.0
    assert result.lower == 0.0 and result.upper == 0.0
