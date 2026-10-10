from __future__ import annotations

from agentqa.agent.healing.cascade import CascadeRanker
from agentqa.agent.healing.features import FEATURE_KEYS, candidate_features, descriptor_signature, name_similarity
from agentqa.agent.healing.healer import AsyncHeuristicRanker, HealContext, HealDecision, Healer, build_runtime_target
from agentqa.agent.healing.model import ModelRanker
from agentqa.agent.healing.ranker import HeuristicRanker, RankContext, filter_candidates, score_candidates
from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.contracts.ports import DecisionModelPort


def build_ranker(profile: CalibrationProfile, decision: DecisionModelPort | None):
    heuristic = HeuristicRanker(profile)
    if profile.ranker == RankerKind.HEURISTIC:
        return AsyncHeuristicRanker(heuristic)
    if decision is None:
        return AsyncHeuristicRanker(heuristic)
    model = ModelRanker(decision, profile)
    if profile.ranker == RankerKind.LLM:
        return model
    return CascadeRanker(heuristic, model, profile)


def build_healer(profile: CalibrationProfile, *, decision: DecisionModelPort | None = None) -> Healer:
    return Healer(profile=profile, ranker=build_ranker(profile, decision))


__all__ = [
    "FEATURE_KEYS",
    "AsyncHeuristicRanker",
    "CascadeRanker",
    "HealContext",
    "HealDecision",
    "Healer",
    "HeuristicRanker",
    "ModelRanker",
    "RankContext",
    "build_healer",
    "build_ranker",
    "build_runtime_target",
    "candidate_features",
    "descriptor_signature",
    "filter_candidates",
    "name_similarity",
    "score_candidates",
]
