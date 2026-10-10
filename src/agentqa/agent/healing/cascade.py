from __future__ import annotations

from agentqa.agent.healing.model import ModelRanker
from agentqa.agent.healing.ranker import HeuristicRanker, RankContext
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.contracts.healing import HealingRanking, RankingOutcome
from agentqa.contracts.identity import TargetDescriptor


class CascadeRanker:
    def __init__(self, heuristic: HeuristicRanker, model: ModelRanker, profile: CalibrationProfile) -> None:
        self._heuristic = heuristic
        self._model = model
        self._profile = profile

    async def rank(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: RankContext,
    ) -> HealingRanking:
        base = self._heuristic.rank(descriptor, scene, context)
        if base.outcome == RankingOutcome.RECOVER and (base.margin is None or base.margin >= self._profile.margin_min):
            return base
        model_result = await self._model.rank(descriptor, scene, context)
        if model_result.outcome == RankingOutcome.RECOVER:
            return model_result.model_copy(update={"ranker": RankerKind.CASCADE})
        if base.outcome == RankingOutcome.RECOVER:
            return base
        return model_result.model_copy(update={"ranker": RankerKind.CASCADE})
