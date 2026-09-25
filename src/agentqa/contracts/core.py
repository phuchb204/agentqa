from typing import Literal

from pydantic import BaseModel

ObservationMode = Literal["a11y", "vision", "hybrid"]
ActionType = Literal["navigate", "click", "fill", "finish"]


class ObservationSnapshot(BaseModel):
    mode: ObservationMode
    url: str
    title: str
    text: str
    element_count: int
    size_bytes: int
    truncated: bool


class Action(BaseModel):
    type: ActionType
    target: str | None = None
    value: str | None = None
    rationale: str = ""


class StepResult(BaseModel):
    index: int
    action: Action
    ok: bool
    error: str | None = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    observation_bytes: int = 0
