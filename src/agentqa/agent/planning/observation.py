from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from agentqa.contracts.observation import Modality, ModalityAudit, SemanticCandidate


@dataclass(frozen=True)
class AgentObservation:
    observation_id: UUID
    scene_version: int
    modality: Modality
    candidates: list[SemanticCandidate] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    truncated: bool = False
    none_context_sentinel: bool = False
    audit: ModalityAudit | None = None

    def candidate(self, candidate_id: str) -> SemanticCandidate | None:
        return next((item for item in self.candidates if item.candidate_id == candidate_id), None)
