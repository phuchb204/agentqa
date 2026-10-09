from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import field_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.values import StrictModel

CAPABILITY_SCHEMA_VERSION = "capability-receipt/1"


class CapabilityKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    STRUCTURED_OUTPUT = "structured_output"
    USAGE = "usage"
    CACHE = "cache"
    SESSION = "session"


class CapabilityStatus(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class CapabilityReceipt(StrictModel):
    schema_version: str = CAPABILITY_SCHEMA_VERSION
    receipt_id: UUID
    route: ProviderRoute
    model_requested: str
    model_resolved: str | None = None
    adapter_schema_version: str
    request_digest: str
    result_digest: str
    capabilities: dict[CapabilityKind, CapabilityStatus] = {}
    version_identity: str = "unverified"
    route_epoch: str
    verified_at: datetime
    expires_at: datetime
    deployment_version: str | None = None
    blocked_reason: str | None = None

    @field_validator("verified_at", "expires_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AgentQAValidationError(
                [field_error(("expires_at",), ErrorCode.INPUT_INVALID, "Timestamp phải có timezone")]
            )
        return value

    def capability_status(self, kind: CapabilityKind) -> CapabilityStatus:
        return self.capabilities.get(kind, CapabilityStatus.UNVERIFIED)

    def is_valid_at(self, now: datetime) -> bool:
        return self.expires_at > now

    def image_ready_at(self, now: datetime) -> bool:
        return self.capability_status(CapabilityKind.IMAGE) is CapabilityStatus.VERIFIED and self.is_valid_at(now)

    def sanitized_view(self) -> dict[str, str]:
        return {
            "receipt_id": str(self.receipt_id),
            "route": self.route.value,
            "model_requested": self.model_requested,
            "model_resolved": self.model_resolved or "",
            "adapter_schema_version": self.adapter_schema_version,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "version_identity": self.version_identity,
            "route_epoch": self.route_epoch,
            "blocked_reason": self.blocked_reason or "",
        }
