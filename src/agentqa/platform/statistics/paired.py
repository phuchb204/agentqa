from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEFAULT_REPLICATES = 10_000


@dataclass(frozen=True)
class PairedResult:
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence: float
    replicates: int
    seed: int
    strata: int
    pairs: int
    sufficient_support: bool
    reason: str | None = None
    p_value: float | None = None


def paired_bootstrap(
    pairs_by_stratum: Mapping[str, Sequence[tuple[float, float]]],
    *,
    confidence: float = 0.95,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = 20261010,
) -> PairedResult:
    strata = {name: list(pairs) for name, pairs in pairs_by_stratum.items() if pairs}
    total_pairs = sum(len(pairs) for pairs in strata.values())
    if len(strata) < 1 or total_pairs == 0:
        return PairedResult(
            estimate=None,
            lower=None,
            upper=None,
            confidence=confidence,
            replicates=replicates,
            seed=seed,
            strata=len(strata),
            pairs=total_pairs,
            sufficient_support=False,
            reason="insufficient_support",
        )
    import numpy as np

    rng = np.random.default_rng(seed)
    names = sorted(strata)
    observed = _mean_delta([pair for name in names for pair in strata[name]])
    draws: list[float] = []
    for _ in range(replicates):
        sampled: list[tuple[float, float]] = []
        for _index in range(len(names)):
            name = names[int(rng.integers(0, len(names)))]
            sampled.extend(strata[name])
        draws.append(_mean_delta(sampled))
    lower = float(np.quantile(draws, (1.0 - confidence) / 2.0))
    upper = float(np.quantile(draws, 1.0 - (1.0 - confidence) / 2.0))
    array = np.asarray(draws)
    below = float(np.mean(array <= 0.0))
    above = float(np.mean(array >= 0.0))
    p_value = min(1.0, max(2.0 * min(below, above), 1.0 / replicates))
    return PairedResult(
        estimate=float(observed),
        lower=lower,
        upper=upper,
        confidence=confidence,
        replicates=replicates,
        seed=seed,
        strata=len(strata),
        pairs=total_pairs,
        sufficient_support=True,
        p_value=p_value,
    )


def _mean_delta(pairs: Sequence[tuple[float, float]]) -> float:
    return sum(left - right for left, right in pairs) / len(pairs)
