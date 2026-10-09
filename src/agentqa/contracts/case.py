from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentqa.contracts.actions import Operation, SideEffectClass
from agentqa.contracts.errors import AgentQAValidationError, ErrorCode, field_error
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import JsonValue, StrictModel, Taint, ValueExpr, ValueType
from agentqa.contracts.verification import AssertionSpec, Comparator, WaitPolicy


class Provenance(StrEnum):
    USER = "user"
    DOCUMENT = "document"
    INFERRED = "inferred"


class AnchorType(StrEnum):
    SECTION = "section"
    PAGE = "page"
    PARAGRAPH = "paragraph"


class SourceAnchor(StrictModel):
    type: AnchorType
    value: str | int


class SourceRef(StrictModel):
    source_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor: SourceAnchor
    quote_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: Provenance
    confirmation_ref: str | None = None


class RequirementContent(StrictModel):
    logical_key: str
    text: str
    source_refs: list[str] = []
    acceptance_statements: list[str] = []
    tags: list[str] = []


class ParameterDef(StrictModel):
    type: ValueType
    required: bool = True
    default: JsonValue | None = None


class ComparisonCondition(StrictModel):
    kind: Literal["comparison"]
    comparator: Comparator
    target: TargetDescriptor | None = None
    expected: ValueExpr | None = None


class CaptureCondition(StrictModel):
    kind: Literal["capture"]
    name: str


class AndCondition(StrictModel):
    kind: Literal["and"]
    conditions: list[Condition]


class OrCondition(StrictModel):
    kind: Literal["or"]
    conditions: list[Condition]


class NotCondition(StrictModel):
    kind: Literal["not"]
    condition: Condition


Condition = Annotated[
    ComparisonCondition | CaptureCondition | AndCondition | OrCondition | NotCondition,
    Field(discriminator="kind"),
]


class PostconditionClassification(StrEnum):
    PROCESS = "process"
    BUSINESS = "business"


class PostconditionDef(StrictModel):
    classification: PostconditionClassification
    condition: Condition
    source_refs: list[str] = []


class ContextRef(StrictModel):
    page: str | None = None
    frame: str | None = None


class ActionNode(StrictModel):
    kind: Literal["action"]
    id: str
    operation: Operation
    context: ContextRef | None = None
    target: TargetDescriptor | None = None
    value: ValueExpr | None = None
    wait: WaitPolicy | None = None
    side_effect: SideEffectClass
    postconditions: list[str] = []


class CheckpointNode(StrictModel):
    kind: Literal["checkpoint"]
    id: str
    assertions: list[AssertionSpec]


class CaptureOutput(StrictModel):
    name: str
    type: ValueType
    taint: Taint = Taint.INTERNAL


class CaptureNode(StrictModel):
    kind: Literal["capture"]
    id: str
    probe: ComparisonCondition
    output: CaptureOutput


class BranchNode(StrictModel):
    kind: Literal["branch"]
    id: str
    condition: Condition
    then_nodes: list[CaseNode] = []
    else_nodes: list[CaseNode] = []


class LoopNode(StrictModel):
    kind: Literal["loop"]
    id: str
    condition: Condition
    max_iterations: int
    body: list[CaseNode] = []


CaseNode = Annotated[
    ActionNode | CheckpointNode | CaptureNode | BranchNode | LoopNode,
    Field(discriminator="kind"),
]


class Completion(StrictModel):
    required_nodes: list[str]
    required_assertions: list[str] = []


class FixtureReceipt(StrictModel):
    fixture_ref: str
    namespace: str
    action: Literal["prepare", "reset", "cleanup"]
    ok: bool
    detail: str | None = None


class CaseContent(StrictModel):
    schema_version: Literal["case/1"]
    logical_key: str
    title: str
    goal: str
    requirements: list[str]
    source_defs: dict[str, SourceRef] = {}
    postcondition_defs: dict[str, PostconditionDef] = {}
    parameter_defs: dict[str, ParameterDef] = {}
    fixture_refs: list[str] = []
    preconditions: list[str] = []
    nodes: list[CaseNode]
    completion: Completion
    required_capabilities: list[str] = []

    @model_validator(mode="after")
    def require_content_identity(self) -> CaseContent:
        if not self.logical_key.strip():
            raise AgentQAValidationError(
                [field_error(("logical_key",), ErrorCode.INPUT_INVALID, "logical_key không được rỗng")]
            )
        return self
