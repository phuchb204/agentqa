from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HolmResult:
    labels: list[str]
    p_values: list[float]
    adjusted: list[float]
    rejected: list[bool]
    alpha: float


def holm_adjust(labels: list[str], p_values: list[float], *, alpha: float = 0.05) -> HolmResult:
    if len(labels) != len(p_values):
        raise ValueError("labels và p_values phải cùng độ dài")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha phải nằm trong (0, 1)")
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    m = len(p_values)
    adjusted = [0.0] * m
    rejected = [False] * m
    running = 0.0
    still_rejecting = True
    for rank, index in enumerate(order):
        candidate = (m - rank) * p_values[index]
        running = max(running, min(candidate, 1.0))
        adjusted[index] = running
        if still_rejecting and p_values[index] <= alpha / (m - rank):
            rejected[index] = True
        else:
            still_rejecting = False
    return HolmResult(labels=list(labels), p_values=list(p_values), adjusted=adjusted, rejected=rejected, alpha=alpha)
