from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.values import SecretValue, StrictModel, ValueExpr


class LocatorKind(StrEnum):
    ROLE = "role"
    LABEL = "label"
    TEST_ID = "test_id"
    CSS = "css"
    TEXT = "text"


class LocatorAlternative(StrictModel):
    kind: LocatorKind
    value: str


class EntityScope(StrictModel):
    field: str
    value: ValueExpr

    @model_validator(mode="after")
    def reject_secret(self) -> EntityScope:
        if isinstance(self.value, SecretValue):
            raise AgentQAValidationError([field_error(("entity_scope", "value"), ErrorCode.SECRET_INTERPOLATION)])
        return self


class TargetDescriptor(StrictModel):
    intent: str
    role: str | None = None
    name: str | None = None
    entity_scope: EntityScope | None = None
    attributes: dict[str, str] = {}
    locators: list[LocatorAlternative] = []
    visual_ref: str | None = None

    @model_validator(mode="after")
    def require_intent(self) -> TargetDescriptor:
        if not self.intent.strip():
            raise AgentQAValidationError([field_error(("intent",), ErrorCode.INPUT_INVALID)])
        return self


class CandidateProof(StrictModel):
    candidate_id: UUID
    score: float
    attributes: dict[str, str] = {}
    evidence_ref: str | None = None
