from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from agentqa.contracts.values import StrictModel


class ArtifactKind(StrEnum):
    EVIDENCE = "evidence"
    TRACE = "trace"
    SCREENSHOT = "screenshot"
    REPORT = "report"
    EXPORT = "export"
    SOURCE = "source"


class IntegrityStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


class RetentionClass(StrEnum):
    RUN = "run"
    WORKSPACE = "workspace"
    RESEARCH = "research"


class ArtifactMetadata(StrictModel):
    artifact_id: UUID
    kind: ArtifactKind
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int
    media_type: str
    integrity: IntegrityStatus
    retention: RetentionClass
    redacted: bool
    created_at: datetime
