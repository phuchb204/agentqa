from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.values import JsonValue, StrictModel


class ProviderRoute(StrEnum):
    OPENCODE_GO = "opencode_go"
    OPENCODE_ZEN = "opencode_zen"


class MessagePurpose(StrEnum):
    OBSERVE = "observe"
    DECIDE = "decide"
    PROPOSE = "propose"
    AUTHORING = "authoring"
    CONFORMANCE = "conformance"


class ModelCallOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Usage(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


class PriceSnapshot(StrictModel):
    currency: str
    input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None
    basis: str


class ModelCallRecord(StrictModel):
    call_id: UUID
    group_id: UUID | None = None
    attempt: int = 1
    purpose: MessagePurpose
    requested_model: str
    resolved_model: str | None = None
    route: ProviderRoute
    session_id: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    usage: Usage | None = None
    price: PriceSnapshot | None = None
    outcome: ModelCallOutcome = ModelCallOutcome.SUCCEEDED
    error_code: ErrorCode | None = None
    started_at: datetime
    ended_at: datetime | None = None


class GenerationRequest(StrictModel):
    purpose: MessagePurpose
    schema_name: str
    schema_version: str
    prompt_ref: str
    input_refs: list[str] = []
    max_output_tokens: int | None = None


class GenerationResult(StrictModel):
    route: ProviderRoute
    model: str
    output_ref: str | None = None
    structured: dict[str, JsonValue] | None = None
    usage: Usage | None = None


class DecisionQuestion(StrictModel):
    question_id: str
    prompt_ref: str
    options: list[str] = []


class DecisionResult(StrictModel):
    answers: dict[str, JsonValue] = {}
    usage: Usage | None = None
