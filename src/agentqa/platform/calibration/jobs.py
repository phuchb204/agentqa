from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from itertools import product
from typing import Any, Protocol

from agentqa.platform.calibration.models import (
    CalibrationManifest,
    CalibrationTrial,
    CandidateResult,
    TrialLabels,
)
from agentqa.platform.calibration.profiles import build_receipt, rank_candidates
from agentqa.platform.statistics.samples import (
    sample_size_from_conservative_bound,
    sample_size_from_pilot_rows,
)


class CalibrationRunner(Protocol):
    async def run_trial(self, *, candidate: CandidateResult, case_key: str, family: str, split: str) -> TrialLabels: ...


class SuiteCalibrationRunner:
    def __init__(
        self,
        *,
        submit_run: Callable[[CandidateResult, str], Awaitable[str]],
        wait_run: Callable[[str], Awaitable[dict[str, Any]]],
        derive_labels: Callable[[dict[str, Any]], TrialLabels],
    ) -> None:
        self._submit_run = submit_run
        self._wait_run = wait_run
        self._derive_labels = derive_labels

    async def run_trial(self, *, candidate: CandidateResult, case_key: str, family: str, split: str) -> TrialLabels:
        run_id = await self._submit_run(candidate, case_key)
        summary = await self._wait_run(run_id)
        return self._derive_labels(summary)


def enumerate_candidates(manifest: CalibrationManifest) -> list[CandidateResult]:
    space = manifest.search_space
    candidates: list[CandidateResult] = []
    for ranker, min_score, margin, max_candidates in product(
        space.rankers, space.min_score, space.margin_min, space.max_candidates
    ):
        candidate_id = f"{ranker}-{min_score}-{margin}-{max_candidates}"
        candidates.append(
            CandidateResult(
                candidate_id=candidate_id,
                ranker=ranker,
                params={"min_score": min_score, "margin_min": margin, "max_candidates": max_candidates},
            )
        )
    return candidates


def _family_of(case_key: str) -> str:
    return case_key.split(":", 1)[0]


async def run_calibration(
    manifest: CalibrationManifest,
    runner: CalibrationRunner,
    *,
    candidates: Sequence[CandidateResult] | None = None,
) -> dict[str, Any]:
    candidate_list = list(candidates) if candidates is not None else enumerate_candidates(manifest)
    calibration_cases = list(manifest.splits["calibration"])
    pilot_cases = list(manifest.splits.get("pilot", []))
    trials: list[CalibrationTrial] = []
    for candidate in candidate_list:
        for case_key in calibration_cases:
            family = _family_of(case_key)
            labels = await runner.run_trial(candidate=candidate, case_key=case_key, family=family, split="calibration")
            trials.append(
                CalibrationTrial(
                    candidate_id=candidate.candidate_id,
                    case_key=case_key,
                    family=family,
                    split="calibration",
                    labels=labels,
                )
            )
    ranking = rank_candidates(candidate_list, trials, manifest)
    winner_id = ranking[0]["candidate_id"] if ranking else None
    winner = next(candidate for candidate in candidate_list if candidate.candidate_id == winner_id)
    pilot_rates: list[float] = []
    for case_key in pilot_cases:
        labels = await runner.run_trial(candidate=winner, case_key=case_key, family=_family_of(case_key), split="pilot")
        pilot_rates.append(1.0 if labels.false_heal else 0.0)
    if pilot_rates:
        sample_size = sample_size_from_pilot_rows(pilot_rates, precision=0.01).as_dict()
    else:
        sample_size = sample_size_from_conservative_bound(
            manifest.quality_policy.max_false_heal_rate, confidence=manifest.quality_policy.confidence
        ).as_dict()
    receipt = build_receipt(manifest, winner, trials, ranking=ranking, sample_size=sample_size)
    return {"receipt": receipt, "ranking": ranking, "trials": trials}
