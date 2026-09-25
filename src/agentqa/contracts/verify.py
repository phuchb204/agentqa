from typing import Literal

from pydantic import BaseModel

AssertionKind = Literal["text_visible", "url_contains"]
AssertionStatus = Literal["passed", "failed", "error"]


class AssertionSpec(BaseModel):
    id: str
    kind: AssertionKind
    value: str
    description: str = ""


class AssertionResult(BaseModel):
    assertion_id: str
    status: AssertionStatus
    detail: str = ""


class MutationChange(BaseModel):
    kind: str
    selector: str | None = None
    before: str | None = None
    after: str | None = None


class MutationSpec(BaseModel):
    id: str
    variant: str
    description: str = ""
    changes: list[MutationChange] = []
    ground_truth: str = ""
