from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agentqa.contracts.case import SourceAnchor
from agentqa.contracts.values import StrictModel


class SourcePrivacyClass(StrEnum):
    STANDARD = "standard"
    SENSITIVE = "sensitive"


class SourceRevisionState(StrEnum):
    QUARANTINED = "quarantined"
    VALIDATED = "validated"
    EXTRACTED = "extracted"
    UNEXTRACTABLE = "unextractable"
    REJECTED = "rejected"


class SegmentPrivacy(StrEnum):
    SAFE = "safe"
    REDACTED = "redacted"


class SourceSegment(StrictModel):
    ordinal: int = Field(ge=0)
    anchor: SourceAnchor
    text: str
    text_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    privacy: SegmentPrivacy = SegmentPrivacy.SAFE


class ExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    UNEXTRACTABLE = "unextractable"
    REJECTED = "rejected"
