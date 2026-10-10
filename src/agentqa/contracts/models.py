from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
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
    FINISH = "finish"
    REPAIR = "repair"
    VALUE_GENERATION = "value_generation"
    DIAGNOSTIC = "diagnostic"


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


class GenerationMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class GenerationTextPart(StrictModel):
    kind: Literal["text"] = "text"
    text: str


class GenerationImagePart(StrictModel):
    kind: Literal["image"] = "image"
    ref: str
    media_type: str
    sha256: str


GenerationPart = Annotated[GenerationTextPart | GenerationImagePart, Field(discriminator="kind")]


class GenerationMessage(StrictModel):
    role: GenerationMessageRole
    parts: list[GenerationPart] = []


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON_OBJECT = "json_object"


class GenerationRequest(StrictModel):
    purpose: MessagePurpose
    schema_name: str
    schema_version: str
    prompt_ref: str
    input_refs: list[str] = []
    max_output_tokens: int | None = None
    output_format: OutputFormat = OutputFormat.TEXT
    messages: list[GenerationMessage] = []


class GenerationResult(StrictModel):
    route: ProviderRoute
    model: str
    model_resolved: str | None = None
    output_ref: str | None = None
    raw_text: str | None = None
    structured: dict[str, JsonValue] | None = None
    usage: Usage | None = None


class DecisionKind(StrEnum):
    CHOICE = "choice"
    NOUL = "noul"
    SCORE = "score"


class ChoiceQuestion(StrictModel):
    kind: Literal[DecisionKind.CHOICE] = DecisionKind.CHOICE
    question_id: str
    instructions: str
    criteria: dict[str, JsonValue] = {}

    @field_validator("question_id")
    @classmethod
    def require_question_id(cls, value: str) -> str:
        if not value.strip():
            raise AgentQAValidationError(
                [field_error(("question_id",), ErrorCode.INPUT_INVALID, "Question ID không được rỗng")]
            )
        return value


class NoulQuestion(StrictModel):
    kind: Literal[DecisionKind.NOUL] = DecisionKind.NOUL
    question_id: str
    instructions: str


class ScoreQuestion(StrictModel):
    kind: Literal[DecisionKind.SCORE] = DecisionKind.SCORE
    question_id: str
    instructions: str
    criteria: list[JsonValue] = []


DecisionQuestion = Annotated[ChoiceQuestion | NoulQuestion | ScoreQuestion, Field(discriminator="kind")]


def _require_probability(path: tuple[str | int, ...], value: float) -> float:
    if value != value or value in (float("inf"), float("-inf")):
        raise AgentQAValidationError([field_error(path, ErrorCode.PROVIDER_SCHEMA, "Giá trị xác suất không hữu hạn")])
    if value < 0.0 or value > 1.0:
        raise AgentQAValidationError([field_error(path, ErrorCode.PROVIDER_SCHEMA, "Xác suất ngoài [0, 1]")])
    return value


class ChoiceAnswer(StrictModel):
    kind: Literal[DecisionKind.CHOICE] = DecisionKind.CHOICE
    choice: str
    confidence: float
    probabilities: dict[str, float] = {}

    @field_validator("confidence")
    @classmethod
    def check_confidence(cls, value: float) -> float:
        return _require_probability(("confidence",), value)

    @field_validator("probabilities")
    @classmethod
    def check_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        return {key: _require_probability(("probabilities", key), item) for key, item in value.items()}


class NoulAnswer(StrictModel):
    kind: Literal[DecisionKind.NOUL] = DecisionKind.NOUL
    noul: float

    @field_validator("noul")
    @classmethod
    def check_noul(cls, value: float) -> float:
        return _require_probability(("noul",), value)


class ScoreAnswer(StrictModel):
    kind: Literal[DecisionKind.SCORE] = DecisionKind.SCORE
    score: float
    confidence: float
    legend: dict[str, JsonValue] = {}
    probabilities: dict[str, float] = {}

    @field_validator("score")
    @classmethod
    def check_score(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise AgentQAValidationError([field_error(("score",), ErrorCode.PROVIDER_SCHEMA, "Score không hữu hạn")])
        return value

    @field_validator("confidence")
    @classmethod
    def check_confidence(cls, value: float) -> float:
        return _require_probability(("confidence",), value)

    @field_validator("probabilities")
    @classmethod
    def check_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        return {key: _require_probability(("probabilities", key), item) for key, item in value.items()}


DecisionAnswer = Annotated[ChoiceAnswer | NoulAnswer | ScoreAnswer, Field(discriminator="kind")]


class DecisionRequest(StrictModel):
    state: JsonValue
    questions: list[DecisionQuestion] = []


class DecisionResult(StrictModel):
    model: str | None = None
    answers: dict[str, DecisionAnswer] = {}
    usage: Usage | None = None
