from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Denominator:
    n: int
    missing: int
    not_applicable: bool
    reason: str | None = None


def denominator(values: Sequence[Any], *, missing: int = 0) -> Denominator:
    if len(values) == 0:
        return Denominator(n=0, missing=missing, not_applicable=True, reason="empty_denominator")
    return Denominator(n=len(values), missing=missing, not_applicable=False)


@dataclass(frozen=True)
class PriceBasisReport:
    compatible: bool
    bases: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    reason: str | None = None


def check_price_basis(entries: Iterable[dict[str, Any]]) -> PriceBasisReport:
    bases = sorted({str(entry.get("basis")) for entry in entries})
    currencies = sorted({str(entry.get("currency")) for entry in entries})
    if len(bases) > 1:
        return PriceBasisReport(compatible=False, bases=bases, currencies=currencies, reason="mixed_price_basis")
    if len(currencies) > 1:
        return PriceBasisReport(compatible=False, bases=bases, currencies=currencies, reason="mixed_currency")
    return PriceBasisReport(compatible=True, bases=bases, currencies=currencies)


def dedupe_repetitions(
    rows: Sequence[dict[str, Any]], *, key_fields: Sequence[str]
) -> tuple[list[dict[str, Any]], int]:
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(row)
    return unique, duplicates
