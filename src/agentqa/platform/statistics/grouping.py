from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

DEFAULT_REPLICATES = 10_000


@dataclass(frozen=True)
class GroupedEstimate:
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence: float
    replicates: int
    seed: int
    groups: int
    units: int
    sufficient_support: bool
    reason: str | None = None
    group_counts: dict[str, int] = field(default_factory=dict)


def mean_statistic(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def cluster_bootstrap(
    values_by_group: Mapping[str, Sequence[float]],
    *,
    statistic: Callable[[Sequence[float]], float] = mean_statistic,
    confidence: float = 0.95,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = 20261010,
) -> GroupedEstimate:
    groups = {name: list(values) for name, values in values_by_group.items() if values}
    group_counts = {name: len(values) for name, values in groups.items()}
    units = sum(group_counts.values())
    if len(groups) < 2 or units == 0:
        return GroupedEstimate(
            estimate=None,
            lower=None,
            upper=None,
            confidence=confidence,
            replicates=replicates,
            seed=seed,
            groups=len(groups),
            units=units,
            sufficient_support=False,
            reason="insufficient_support",
            group_counts=group_counts,
        )
    import numpy as np

    rng = np.random.default_rng(seed)
    names = sorted(groups)
    observed = statistic([value for name in names for value in groups[name]])
    draws: list[float] = []
    for _ in range(replicates):
        sampled: list[float] = []
        for _index in range(len(names)):
            name = names[int(rng.integers(0, len(names)))]
            sampled.extend(groups[name])
        draws.append(statistic(sampled))
    lower = float(np.quantile(draws, (1.0 - confidence) / 2.0))
    upper = float(np.quantile(draws, 1.0 - (1.0 - confidence) / 2.0))
    return GroupedEstimate(
        estimate=float(observed),
        lower=lower,
        upper=upper,
        confidence=confidence,
        replicates=replicates,
        seed=seed,
        groups=len(groups),
        units=units,
        sufficient_support=True,
        group_counts=group_counts,
    )
