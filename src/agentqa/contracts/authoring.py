from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agentqa.contracts.case import CaseContent, Provenance
from agentqa.contracts.values import StrictModel


class CaseKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"


class ProposalProvenance(StrictModel):
    path: str
    source: Provenance
    ref: str | None = None


class AuthoringProposal(StrictModel):
    title: str
    case_kind: CaseKind
    requirement_keys: list[str] = Field(default_factory=list)
    case: CaseContent
    provenance: list[ProposalProvenance] = Field(default_factory=list)


class AuthoringResult(StrictModel):
    proposals: list[AuthoringProposal] = Field(default_factory=list)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    REJECTED = "rejected"
    APPLIED = "applied"
