from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agentqa.agent.healing.features import descriptor_signature, scope_value
from agentqa.agent.healing.ranker import HeuristicRanker, RankContext
from agentqa.agent.identity.resolver import SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.calibration import CalibrationProfile
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.healing import (
    HealingActor,
    HealingDecision,
    HealingRanking,
    HealingRecord,
    LocatorProposal,
    RankingOutcome,
)
from agentqa.contracts.identity import LocatorAlternative, LocatorKind, TargetDescriptor

STATEFUL_OPERATIONS = frozenset({Operation.CLICK, Operation.CHECK, Operation.UNCHECK, Operation.SELECT})


def stable_opportunity_id(context: HealContext, descriptor: TargetDescriptor) -> str:
    material = digest_content({"node": context.node_id, "intent": descriptor.intent, "name": descriptor.name})
    return f"opp-{material[:16]}"


class RankingPort(Protocol):
    async def rank(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: RankContext,
    ) -> HealingRanking: ...


class AsyncHeuristicRanker:
    def __init__(self, heuristic: HeuristicRanker) -> None:
        self._heuristic = heuristic

    async def rank(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: RankContext,
    ) -> HealingRanking:
        return self._heuristic.rank(descriptor, scene, context)


@dataclass(frozen=True)
class HealContext:
    node_id: str
    actor: HealingActor
    operation: Operation | None = None
    frame_key: str | None = None
    scene_version: int | None = None


@dataclass(frozen=True)
class HealDecision:
    record: HealingRecord
    recovered_target: TargetDescriptor | None

    @property
    def recovered(self) -> bool:
        return self.record.decision == HealingDecision.RECOVERED


def build_runtime_target(descriptor: TargetDescriptor, candidate: SceneCandidate) -> TargetDescriptor:
    locators: list[LocatorAlternative] = []
    test_id = candidate.attributes.get("data-testid")
    element_id = candidate.attributes.get("id")
    if test_id:
        locators.append(LocatorAlternative(kind=LocatorKind.TEST_ID, value=test_id))
    elif element_id:
        locators.append(LocatorAlternative(kind=LocatorKind.CSS, value=f"#{element_id}"))
    return descriptor.model_copy(
        update={
            "name": candidate.name if candidate.name else descriptor.name,
            "locators": locators,
            "attributes": {},
        }
    )


class Healer:
    def __init__(
        self,
        *,
        profile: CalibrationProfile,
        ranker: RankingPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._profile = profile
        self._ranker = ranker
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def profile(self) -> CalibrationProfile:
        return self._profile

    async def recover(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: HealContext,
    ) -> HealDecision:
        rank_context = RankContext(node_id=context.node_id, operation=context.operation, frame_key=context.frame_key)
        try:
            ranking = await self._ranker.rank(descriptor, scene, rank_context)
        except Exception as error:
            return self._refuse(
                descriptor,
                context,
                ranking=None,
                reason="ranking_error",
                error=f"{type(error).__name__}:{error}",
            )
        if ranking.outcome != RankingOutcome.RECOVER:
            reason = ranking.reason or ranking.outcome.value
            return self._refuse(descriptor, context, ranking=ranking, reason=reason)
        chosen_id = ranking.scores[0].candidate_id
        candidate = next((item for item in scene if item.candidate_id == chosen_id), None)
        if candidate is None:
            return self._refuse(descriptor, context, ranking=ranking, reason="candidate_stale")
        checks = admission_checks(descriptor, candidate, context)
        if checks:
            return self._refuse(
                descriptor,
                context,
                ranking=ranking,
                reason=f"admission_rejected:{checks[0]}",
            )
        recovered = build_runtime_target(descriptor, candidate)
        record = HealingRecord(
            opportunity_id=stable_opportunity_id(context, descriptor),
            attempt_id=f"heal-{uuid4().hex}",
            actor=context.actor,
            node_id=context.node_id,
            decision=HealingDecision.RECOVERED,
            ranking=ranking,
            expected_signature=descriptor_signature(descriptor),
            actual_signature=candidate.stable_signature(),
            original_target=descriptor,
            actual_target=recovered,
            guard_checks=guard_checks(descriptor, candidate, context),
            postconditions_ok=None,
            proposal=LocatorProposal(
                node_id=context.node_id,
                intent=descriptor.intent,
                proposed=recovered,
                locator=recovered.locators[0] if recovered.locators else None,
            ),
            recorded_at=self._clock(),
        )
        return HealDecision(record=record, recovered_target=recovered)

    def _refuse(
        self,
        descriptor: TargetDescriptor,
        context: HealContext,
        *,
        ranking: HealingRanking | None,
        reason: str,
        error: str | None = None,
    ) -> HealDecision:
        record = HealingRecord(
            opportunity_id=stable_opportunity_id(context, descriptor),
            attempt_id=f"heal-{uuid4().hex}",
            actor=context.actor,
            node_id=context.node_id,
            decision=HealingDecision.REFUSED,
            ranking=ranking,
            expected_signature=descriptor_signature(descriptor),
            original_target=descriptor,
            guard_checks=[],
            refusal_reason=reason,
            error=error,
            recorded_at=self._clock(),
        )
        return HealDecision(record=record, recovered_target=None)


def admission_checks(descriptor: TargetDescriptor, candidate: SceneCandidate, context: HealContext) -> list[str]:
    failures: list[str] = []
    if context.frame_key is not None and candidate.frame_key is not None and candidate.frame_key != context.frame_key:
        failures.append("frame_mismatch")
    if descriptor.role is not None and (candidate.role or "").casefold() != descriptor.role.casefold():
        failures.append("role_mismatch")
    scope = scope_value(descriptor)
    if scope is not None:
        entity_text = candidate.entity_text if candidate.entity_text is not None else candidate.text or ""
        if scope not in entity_text:
            failures.append("entity_scope_mismatch")
    if context.operation in STATEFUL_OPERATIONS:
        if not candidate.visible:
            failures.append("state_not_visible")
        if not candidate.enabled:
            failures.append("state_not_enabled")
    return failures


def guard_checks(descriptor: TargetDescriptor, candidate: SceneCandidate, context: HealContext) -> list[str]:
    checks = ["uniqueness", "state"]
    if descriptor.role is not None:
        checks.append("role")
    if scope_value(descriptor) is not None:
        checks.append("entity_scope")
    if context.frame_key is not None:
        checks.append("frame")
    if context.operation in STATEFUL_OPERATIONS:
        checks.append("action_state")
    return checks
