from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from agentqa.contracts.canonical import digest_content


@dataclass(frozen=True)
class SampleSizeReport:
    method: str
    confidence: float
    target_rate: float
    units: int
    assumptions: dict[str, Any] = field(default_factory=dict)
    pilot_digest: str | None = None
    algorithm_version: str = "samples/1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "confidence": self.confidence,
            "target_rate": self.target_rate,
            "units": self.units,
            "assumptions": self.assumptions,
            "pilot_digest": self.pilot_digest,
            "algorithm_version": self.algorithm_version,
        }


def conservative_zero_event_units(target_rate: float, *, confidence: float = 0.95) -> int:
    if not 0.0 < target_rate < 1.0:
        raise ValueError("target_rate phải nằm trong (0, 1)")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence phải nằm trong (0, 1)")
    return math.ceil(math.log(1.0 - confidence) / math.log(1.0 - target_rate))


def sample_size_from_conservative_bound(target_rate: float = 0.01, *, confidence: float = 0.95) -> SampleSizeReport:
    units = conservative_zero_event_units(target_rate, confidence=confidence)
    return SampleSizeReport(
        method="conservative_zero_event_bound",
        confidence=confidence,
        target_rate=target_rate,
        units=units,
        assumptions={"rule": "zero observed errors still bounds rate <= target_rate"},
    )


def sample_size_from_pilot(
    pilot_rate: float,
    *,
    precision: float,
    confidence: float = 0.95,
    pilot_units: int = 0,
    pilot_digest: str | None = None,
) -> SampleSizeReport:
    if not 0.0 <= pilot_rate <= 1.0:
        raise ValueError("pilot_rate phải nằm trong [0, 1]")
    if not 0.0 < precision < 1.0:
        raise ValueError("precision phải nằm trong (0, 1)")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence phải nằm trong (0, 1)")
    z = _z_for_confidence(confidence)
    variance = max(pilot_rate * (1.0 - pilot_rate), 1e-6)
    units = math.ceil((z**2) * variance / (precision**2))
    return SampleSizeReport(
        method="pilot_variance",
        confidence=confidence,
        target_rate=pilot_rate,
        units=max(units, 2),
        assumptions={
            "precision": precision,
            "pilot_rate": pilot_rate,
            "pilot_units": pilot_units,
            "z": z,
        },
        pilot_digest=pilot_digest,
    )


def sample_size_from_pilot_rows(
    pilot_rates: list[float],
    *,
    precision: float,
    confidence: float = 0.95,
) -> SampleSizeReport:
    if not pilot_rates:
        raise ValueError("pilot_rates rỗng")
    rate = sum(pilot_rates) / len(pilot_rates)
    return sample_size_from_pilot(
        rate,
        precision=precision,
        confidence=confidence,
        pilot_units=len(pilot_rates),
        pilot_digest=digest_content(pilot_rates),
    )


def _z_for_confidence(confidence: float) -> float:
    from scipy.stats import norm

    return float(norm.ppf(1.0 - (1.0 - confidence) / 2.0))
