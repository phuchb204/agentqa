from __future__ import annotations

from dataclasses import dataclass

from agentqa.agent.healing.features import FEATURE_KEYS, candidate_features, scope_value
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.contracts.healing import HealingCandidateScore, HealingRanking, RankingOutcome
from agentqa.contracts.identity import TargetDescriptor

STATEFUL_OPERATIONS = frozenset(
    {
        Operation.CLICK,
        Operation.CHECK,
        Operation.UNCHECK,
        Operation.SELECT,
        Operation.FILL,
        Operation.UPLOAD,
    }
)


@dataclass(frozen=True)
class RankContext:
    node_id: str
    operation: Operation | None = None
    frame_key: str | None = None


def weights_dict(profile: CalibrationProfile) -> dict[str, float]:
    weights = profile.weights
    return {
        "role": weights.role,
        "name": weights.name,
        "context": weights.context,
        "stable_attribute": weights.stable_attribute,
        "geometry": weights.geometry,
    }


def _identity_key(candidate: SceneCandidate) -> tuple[str, str]:
    return ((candidate.role or "").casefold(), (candidate.name or "").strip().casefold())


def _role_scope_match(descriptor: TargetDescriptor, candidate: SceneCandidate) -> bool:
    if descriptor.role is not None and (candidate.role or "").casefold() != descriptor.role.casefold():
        return False
    scope = scope_value(descriptor)
    if scope is not None:
        entity_text = candidate.entity_text if candidate.entity_text is not None else candidate.text or ""
        if scope not in entity_text:
            return False
    return True


def has_duplicate_identity(
    descriptor: TargetDescriptor,
    kept: list[tuple[SceneCandidate, HealingCandidateScore, CandidateView]],
    min_score: float,
) -> bool:
    if not kept:
        return False
    key = _identity_key(kept[0][0])
    matches = 0
    for candidate, score, _ in kept:
        if score.score < min_score:
            continue
        if _identity_key(candidate) != key:
            continue
        if not _role_scope_match(descriptor, candidate):
            continue
        matches += 1
        if matches >= 2:
            return True
    return False


def filter_candidates(
    descriptor: TargetDescriptor,
    scene: list[SceneCandidate],
    context: RankContext,
) -> list[SceneCandidate]:
    filtered: list[SceneCandidate] = []
    stateful = context.operation in STATEFUL_OPERATIONS
    for candidate in scene:
        if (
            context.frame_key is not None
            and candidate.frame_key is not None
            and candidate.frame_key != context.frame_key
        ):
            continue
        if stateful and (not candidate.visible or not candidate.enabled):
            continue
        filtered.append(candidate)
    return filtered


def score_candidates(
    descriptor: TargetDescriptor,
    candidates: list[SceneCandidate],
    profile: CalibrationProfile,
    context: RankContext,
) -> list[tuple[SceneCandidate, HealingCandidateScore, CandidateView]]:
    weights = weights_dict(profile)
    scored = []
    for candidate in candidates:
        features = candidate_features(descriptor, candidate, frame_key=context.frame_key)
        coverage = features.coverage(weights)
        score = features.weighted_score(weights)
        view = CandidateView(coverage=coverage)
        scored.append(
            (
                candidate,
                HealingCandidateScore(
                    candidate_id=candidate.candidate_id,
                    score=score,
                    feature_scores={key: features.scores[key] for key in FEATURE_KEYS if key in features.scores},
                    missing=sorted(features.missing),
                    reasons=list(features.reasons),
                ),
                view,
            )
        )
    scored.sort(key=lambda item: (-item[1].score, item[0].candidate_id))
    return scored


@dataclass(frozen=True)
class CandidateView:
    coverage: float


class HeuristicRanker:
    def __init__(self, profile: CalibrationProfile) -> None:
        self._profile = profile

    @property
    def profile(self) -> CalibrationProfile:
        return self._profile

    def rank(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: RankContext,
    ) -> HealingRanking:
        candidates = filter_candidates(descriptor, scene, context)
        scored = score_candidates(descriptor, candidates, self._profile, context)
        truncated = len(scored) > self._profile.max_candidates
        kept = scored[: self._profile.max_candidates]
        scores = [item[1] for item in kept]
        margin = None
        if len(scores) >= 2:
            margin = round(scores[0].score - scores[1].score, 4)
        duplicate_identity = has_duplicate_identity(descriptor, kept, self._profile.min_score)
        outcome, reason = self._decide(scores, [item[2] for item in kept], margin, duplicate_identity)
        return HealingRanking(
            ranker=RankerKind.HEURISTIC,
            profile_id=self._profile.profile_id,
            profile_version=self._profile.version,
            outcome=outcome,
            scores=scores,
            margin=margin,
            truncated=truncated,
            total_candidates=len(scored),
            reason=reason,
        )

    def _decide(
        self,
        scores: list[HealingCandidateScore],
        views: list[CandidateView],
        margin: float | None,
        duplicate_identity: bool,
    ) -> tuple[RankingOutcome, str | None]:
        if not scores:
            return RankingOutcome.NONE, "no_candidate"
        if views[0].coverage < self._profile.min_coverage:
            return RankingOutcome.NEED_MORE_CONTEXT, "missing_features"
        if len(scores) > 1 and margin is not None and margin < self._profile.margin_min:
            return RankingOutcome.REFUSE, "ambiguous_margin"
        if duplicate_identity:
            return RankingOutcome.REFUSE, "duplicate_identity"
        if scores[0].score < self._profile.min_score:
            return RankingOutcome.REFUSE, "low_score"
        return RankingOutcome.RECOVER, None
