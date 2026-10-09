from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from agentqa.agent.history import ActionHistory
from agentqa.agent.planning.observation import AgentObservation
from agentqa.agent.planning.planner import PlanningPlan
from agentqa.contracts.actions import Operation
from agentqa.contracts.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
)
from agentqa.contracts.observation import Actionability
from agentqa.contracts.policies import (
    AgentProposal,
    PolicyKind,
    PolicyOutcome,
    PolicyProfile,
    ProposalKind,
)
from agentqa.contracts.ports import DecisionModelPort
from agentqa.models.wire import ModelTransportError

SENTINEL_CHOICE = "none"

ROLE_OPERATIONS: dict[str, tuple[Operation, ...]] = {
    "button": (Operation.CLICK,),
    "link": (Operation.CLICK,),
    "listitem": (Operation.CLICK,),
    "textbox": (Operation.FILL,),
    "combobox": (Operation.SELECT,),
    "checkbox": (Operation.CHECK,),
    "radio": (Operation.CHECK,),
}


@dataclass(frozen=True)
class CascadePair:
    pair_id: str
    operation: Operation
    candidate_id: str
    intent: str


def enumerate_pairs(candidates: list) -> list[CascadePair]:
    pairs: list[CascadePair] = []
    for candidate in candidates:
        if candidate.provenance == "engine":
            continue
        if not candidate.visible or candidate.actionability in (Actionability.DISABLED, Actionability.OFFSCREEN):
            continue
        operations = ROLE_OPERATIONS.get(candidate.role)
        if not operations:
            continue
        for operation in operations:
            pairs.append(
                CascadePair(
                    pair_id=f"p{len(pairs)}",
                    operation=operation,
                    candidate_id=candidate.candidate_id,
                    intent=candidate.name or candidate.role,
                )
            )
    return pairs


class JevCascadePolicy:
    def __init__(
        self,
        jev: DecisionModelPort,
        *,
        profile: PolicyProfile,
        fallback=None,
    ) -> None:
        self._jev = jev
        self._profile = profile
        self._fallback = fallback

    async def propose(
        self,
        *,
        observation: AgentObservation,
        plan: PlanningPlan,
        history: ActionHistory,
    ) -> PolicyOutcome:
        if observation.truncated or observation.none_context_sentinel:
            return await self._escalate(
                "observation_truncated",
                "Candidate list bị cắt, không chọn pair liều lĩnh",
                observation,
                plan,
                history,
            )
        pairs = enumerate_pairs(observation.candidates)
        if not pairs:
            return await self._escalate(
                "no_valid_pairs",
                "Không có operation/target pair hợp lệ",
                observation,
                plan,
                history,
            )
        criteria = {pair.pair_id: f"{pair.operation.value} '{pair.intent}'" for pair in pairs}
        criteria[SENTINEL_CHOICE] = "none/need_more_context"
        questions = [
            ChoiceQuestion(
                question_id="next_action",
                instructions=(
                    "Chọn một pair operation/target hợp lệ để tiến gần mục tiêu, hoặc none nếu thiếu ngữ cảnh."
                ),
                criteria=criteria,
            ),
            NoulQuestion(question_id="progress", instructions="Mục tiêu của ca đã hoàn thành?"),
        ]
        state = {
            "goal": plan.goal,
            "subgoals": [subgoal.goal for subgoal in plan.subgoals],
            "candidates": json.loads(json.dumps(observation.payload.get("candidates", []), ensure_ascii=False)),
            "history": history.summary(),
        }
        try:
            result = await self._jev.decide(DecisionRequest(state=state, questions=questions))
        except ModelTransportError as error:
            return await self._escalate(
                f"provider:{error.code.value}",
                str(error),
                observation,
                plan,
                history,
            )
        progress_answer = result.answers.get("progress")
        if isinstance(progress_answer, NoulAnswer) and progress_answer.noul >= self._profile.progress_stop:
            return PolicyOutcome(
                kind=ProposalKind.STOP,
                reason="jev_progress",
                detail=f"noul={progress_answer.noul}",
                policy_version=self._profile.version,
            )
        choice = result.answers.get("next_action")
        if not isinstance(choice, ChoiceAnswer):
            return await self._escalate(
                "missing_choice_answer",
                "Thiếu answer cho next_action",
                observation,
                plan,
                history,
            )
        if choice.choice == SENTINEL_CHOICE:
            return await self._escalate(
                "jev_sentinel",
                "Jev trả none/need_more_context",
                observation,
                plan,
                history,
            )
        pair = next((item for item in pairs if item.pair_id == choice.choice), None)
        if pair is None:
            return await self._escalate(
                "unknown_pair",
                f"Choice '{choice.choice}' không thuộc pair đã liệt kê",
                observation,
                plan,
                history,
            )
        probabilities = choice.probabilities
        p_max = max(probabilities.values(), default=0.0)
        ranked = sorted(probabilities.values(), reverse=True)
        margin = ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0] if ranked else 0.0
        below_threshold = (
            choice.confidence < self._profile.confidence_min
            or p_max < self._profile.p_max_min
            or margin < self._profile.margin_min
        )
        if below_threshold:
            return await self._escalate(
                "below_threshold",
                f"confidence={choice.confidence} p_max={p_max} margin={margin}",
                observation,
                plan,
                history,
            )
        proposal = AgentProposal(
            proposal_id=uuid4(),
            policy=PolicyKind.JEV_CASCADE,
            policy_version=self._profile.version,
            plan_version=plan.version,
            operation=pair.operation,
            target_intent=pair.intent,
            candidate_id=pair.candidate_id,
            rationale=f"choice {pair.pair_id}: {pair.operation.value} p={p_max:.2f}",
            confidence=choice.confidence,
        )
        return PolicyOutcome(
            kind=ProposalKind.ACTION,
            proposal=proposal,
            policy_version=self._profile.version,
        )

    async def _escalate(
        self,
        reason: str,
        detail: str,
        observation: AgentObservation,
        plan: PlanningPlan,
        history: ActionHistory,
    ) -> PolicyOutcome:
        if self._profile.allow_degradation and self._fallback is not None:
            outcome = await self._fallback.propose(observation=observation, plan=plan, history=history)
            return outcome.model_copy(
                update={
                    "degraded": True,
                    "reason": outcome.reason or reason,
                    "detail": outcome.detail or detail,
                }
            )
        return PolicyOutcome(
            kind=ProposalKind.FAILED,
            reason=f"escalation_blocked:{reason}",
            detail=detail,
            policy_version=self._profile.version,
        )


__all__ = ["SENTINEL_CHOICE", "CascadePair", "JevCascadePolicy", "enumerate_pairs"]
