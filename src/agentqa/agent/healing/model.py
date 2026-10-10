from __future__ import annotations

from agentqa.agent.healing.ranker import RankContext, filter_candidates
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.contracts.healing import HealingCandidateScore, HealingRanking, RankingOutcome
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.models import ChoiceAnswer, ChoiceQuestion, DecisionRequest
from agentqa.contracts.ports import DecisionModelPort
from agentqa.models.wire import ModelTransportError

NONE_CHOICE = "none"
NEED_CONTEXT_CHOICE = "need_more_context"
SENTINEL_CHOICES = (NONE_CHOICE, NEED_CONTEXT_CHOICE)


class ModelRanker:
    def __init__(self, decision: DecisionModelPort, profile: CalibrationProfile) -> None:
        self._decision = decision
        self._profile = profile

    async def rank(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: RankContext,
    ) -> HealingRanking:
        candidates = filter_candidates(descriptor, scene, context)
        truncated = len(candidates) > self._profile.max_candidates
        kept = candidates[: self._profile.max_candidates]
        question_id = f"heal:{context.node_id}"
        criteria = {candidate.candidate_id: candidate.name or candidate.role or "" for candidate in kept}
        criteria[NONE_CHOICE] = "none"
        criteria[NEED_CONTEXT_CHOICE] = "need_more_context"
        question = ChoiceQuestion(
            question_id=question_id,
            instructions=(
                "Chọn candidate giữ đúng identity mục tiêu (role/entity scope) sau khi locator đổi; "
                "trả none nếu không candidate nào phù hợp hoặc need_more_context nếu thiếu dữ kiện."
            ),
            criteria=criteria,
        )
        state = {
            "intent": descriptor.intent,
            "role": descriptor.role,
            "name": descriptor.name,
            "entity_scope": descriptor.entity_scope.model_dump(mode="json") if descriptor.entity_scope else None,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "role": candidate.role,
                    "name": candidate.name,
                    "text": candidate.text,
                    "entity_text": candidate.entity_text,
                    "attributes": {
                        key: value
                        for key, value in candidate.attributes.items()
                        if key in ("id", "data-testid", "name", "aria-label", "label")
                    },
                }
                for candidate in kept
            ],
            "sentinels": list(SENTINEL_CHOICES),
        }
        try:
            result = await self._decision.decide(DecisionRequest(state=state, questions=[question]))
        except ModelTransportError as error:
            return self._refuse("provider_error", str(error), context, len(kept), truncated)
        answer = result.answers.get(question_id)
        if not isinstance(answer, ChoiceAnswer):
            return self._refuse("missing_answer", "Thiếu answer cho câu hỏi healing", context, len(kept), truncated)
        if answer.choice == NONE_CHOICE:
            return self._outcome(RankingOutcome.NONE, "model_none", context, len(kept), truncated, [])
        if answer.choice == NEED_CONTEXT_CHOICE:
            return self._outcome(
                RankingOutcome.NEED_MORE_CONTEXT, "model_need_more_context", context, len(kept), truncated, []
            )
        if answer.choice not in {candidate.candidate_id for candidate in kept}:
            return self._refuse("unknown_candidate", answer.choice, context, len(kept), truncated)
        if answer.confidence < self._profile.min_score:
            return self._refuse("low_confidence", str(answer.confidence), context, len(kept), truncated)
        probabilities = dict(answer.probabilities)
        margin = None
        if len(probabilities) >= 2:
            ranked = sorted(probabilities.values(), reverse=True)
            margin = round(ranked[0] - ranked[1], 4)
            if margin < self._profile.margin_min:
                return self._refuse("ambiguous_margin", str(margin), context, len(kept), truncated)
        if not probabilities:
            probabilities = {answer.choice: answer.confidence}
        scores = [
            HealingCandidateScore(
                candidate_id=candidate.candidate_id,
                score=round(probabilities.get(candidate.candidate_id, 0.0), 4),
                feature_scores={},
                missing=[],
                reasons=["model_choice" if candidate.candidate_id == answer.choice else "model_probability"],
            )
            for candidate in kept
        ]
        scores.sort(key=lambda item: (-item.score, item.candidate_id))
        return HealingRanking(
            ranker=RankerKind.LLM,
            profile_id=self._profile.profile_id,
            profile_version=self._profile.version,
            outcome=RankingOutcome.RECOVER,
            scores=scores,
            margin=margin,
            truncated=truncated,
            total_candidates=len(candidates),
            reason=None,
        )

    def _refuse(
        self,
        reason: str,
        detail: str,
        context: RankContext,
        kept: int,
        truncated: bool,
    ) -> HealingRanking:
        return self._outcome(RankingOutcome.REFUSE, f"{reason}:{detail}", context, kept, truncated, [])

    def _outcome(
        self,
        outcome: RankingOutcome,
        reason: str,
        context: RankContext,
        kept: int,
        truncated: bool,
        scores: list[HealingCandidateScore],
    ) -> HealingRanking:
        return HealingRanking(
            ranker=RankerKind.LLM,
            profile_id=self._profile.profile_id,
            profile_version=self._profile.version,
            outcome=outcome,
            scores=scores,
            margin=None,
            truncated=truncated,
            total_candidates=kept,
            reason=reason,
        )
