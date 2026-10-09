from __future__ import annotations

from dataclasses import dataclass, field

from agentqa.agent.identity.resolver import CandidateMatch, IdentityResolver, SceneCandidate
from agentqa.contracts.actions import Operation
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import LiteralValue

STATEFUL_OPERATIONS = frozenset({Operation.CLICK, Operation.CHECK, Operation.UNCHECK, Operation.SELECT})


@dataclass(frozen=True)
class GuardContext:
    operation: Operation
    frame_key: str | None = None
    expected_scene_version: int | None = None
    current_scene_version: int | None = None
    entity_scope_value: str | None = None

    @property
    def scene_proof_expired(self) -> bool:
        if self.expected_scene_version is None or self.current_scene_version is None:
            return False
        return self.expected_scene_version != self.current_scene_version


@dataclass(frozen=True)
class GuardProof:
    candidate_id: str
    identity_signature: str
    scene_version: int | None
    reasons: tuple[str, ...]
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "identity_signature": self.identity_signature,
            "scene_version": self.scene_version,
            "reasons": list(self.reasons),
            "score": self.score,
        }


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: ErrorCode | None = None
    reason: str | None = None
    matched: SceneCandidate | None = None
    proof: GuardProof | None = None
    alternates: tuple[CandidateMatch, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "code": self.code.value if self.code else None,
            "reason": self.reason,
            "matched": self.matched.candidate_id if self.matched else None,
            "proof": self.proof.as_dict() if self.proof else None,
            "alternates": [match.candidate.candidate_id for match in self.alternates],
        }


class TargetGuard:
    def __init__(self, resolver: IdentityResolver | None = None) -> None:
        self._resolver = resolver or IdentityResolver()

    def check(
        self,
        descriptor: TargetDescriptor,
        scene: list[SceneCandidate],
        context: GuardContext,
    ) -> GuardDecision:
        if context.scene_proof_expired:
            return GuardDecision(
                allowed=False,
                code=ErrorCode.IDENTITY_MISMATCH,
                reason="scene_proof_expired",
            )
        matches = self._resolver.resolve(descriptor, scene, frame_key=context.frame_key)
        if not matches:
            return GuardDecision(allowed=False, code=ErrorCode.LOCATOR_MISSING, reason="no_candidate")
        if len(matches) > 1:
            return GuardDecision(
                allowed=False,
                code=ErrorCode.LOCATOR_AMBIGUOUS,
                reason="multiple_identities",
                alternates=tuple(matches),
            )
        candidate = matches[0].candidate
        state_reason = self._state_mismatch(descriptor, candidate, context)
        if state_reason is not None:
            return GuardDecision(
                allowed=False,
                code=ErrorCode.IDENTITY_MISMATCH,
                reason=state_reason,
                alternates=tuple(matches),
            )
        return GuardDecision(
            allowed=True,
            matched=candidate,
            proof=GuardProof(
                candidate_id=candidate.candidate_id,
                identity_signature=candidate.stable_signature(),
                scene_version=context.current_scene_version,
                reasons=matches[0].reasons,
                score=matches[0].score,
            ),
        )

    def _state_mismatch(
        self,
        descriptor: TargetDescriptor,
        candidate: SceneCandidate,
        context: GuardContext,
    ) -> str | None:
        scope = self._scope_value(descriptor)
        if context.entity_scope_value and scope != context.entity_scope_value:
            return "entity_scope_mismatch"
        if context.operation in STATEFUL_OPERATIONS:
            if not candidate.visible:
                return "state_not_visible"
            if not candidate.enabled:
                return "state_not_enabled"
        return None

    def _scope_value(self, descriptor: TargetDescriptor) -> str | None:
        if descriptor.entity_scope is None or not isinstance(descriptor.entity_scope.value, LiteralValue):
            return None
        value = descriptor.entity_scope.value.value
        return value if isinstance(value, str) else None
