from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from agentqa.contracts.calibration import RankerKind
from agentqa.contracts.identity import LocatorAlternative, TargetDescriptor
from agentqa.contracts.values import StrictModel


class HealingActor(StrEnum):
    ACTION = "action"
    EVIDENCE = "evidence"


class HealingDecision(StrEnum):
    RECOVERED = "recovered"
    REFUSED = "refused"


class RankingOutcome(StrEnum):
    RECOVER = "recover"
    REFUSE = "refuse"
    NONE = "none"
    NEED_MORE_CONTEXT = "need_more_context"


class HealingCandidateScore(StrictModel):
    candidate_id: str
    score: float
    feature_scores: dict[str, float] = {}
    missing: list[str] = []
    reasons: list[str] = []


class HealingRanking(StrictModel):
    ranker: RankerKind
    profile_id: str
    profile_version: str
    outcome: RankingOutcome
    scores: list[HealingCandidateScore] = []
    margin: float | None = None
    truncated: bool = False
    total_candidates: int = 0
    reason: str | None = None


class LocatorProposal(StrictModel):
    node_id: str
    intent: str
    proposed: TargetDescriptor
    locator: LocatorAlternative | None = None
    source_run_id: UUID | None = None
    evidence_ref: str | None = None


class HealingRecord(StrictModel):
    opportunity_id: str
    attempt_id: str
    actor: HealingActor
    node_id: str
    decision: HealingDecision
    ranking: HealingRanking | None = None
    expected_signature: str | None = None
    actual_signature: str | None = None
    original_target: TargetDescriptor | None = None
    actual_target: TargetDescriptor | None = None
    dispatch_outcome: str | None = None
    guard_checks: list[str] = []
    postconditions_ok: bool | None = None
    refusal_reason: str | None = None
    error: str | None = None
    proposal: LocatorProposal | None = None
    recorded_at: datetime
