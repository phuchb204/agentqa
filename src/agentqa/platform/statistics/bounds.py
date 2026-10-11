from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundResult:
    errors: int
    units: int
    confidence: float
    lower: float | None
    upper: float | None
    method: str
    zero_event: bool


def exact_upper_bound(errors: int, units: int, *, confidence: float = 0.95) -> float | None:
    if units <= 0:
        return None
    if errors < 0 or errors > units:
        raise ValueError("errors phải nằm trong [0, units]")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence phải nằm trong (0, 1)")
    if errors == units:
        return 1.0
    from scipy.stats import beta

    return float(beta.ppf(confidence, errors + 1, units - errors))


def exact_lower_bound(errors: int, units: int, *, confidence: float = 0.95) -> float | None:
    if units <= 0:
        return None
    if errors < 0 or errors > units:
        raise ValueError("errors phải nằm trong [0, units]")
    if errors == 0:
        return 0.0
    from scipy.stats import beta

    return float(beta.ppf(1.0 - confidence, errors, units - errors + 1))


def exact_one_sided(errors: int, units: int, *, confidence: float = 0.95) -> BoundResult:
    return BoundResult(
        errors=errors,
        units=units,
        confidence=confidence,
        lower=exact_lower_bound(errors, units, confidence=confidence),
        upper=exact_upper_bound(errors, units, confidence=confidence),
        method="clopper_pearson_one_sided",
        zero_event=errors == 0,
    )
