from typing import Literal

from pydantic import BaseModel

from agentqa.contracts.core import StepResult
from agentqa.contracts.verify import AssertionResult

RunStatus = Literal["passed", "failed", "error"]


class RunMetrics(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0


class RunVersions(BaseModel):
    app: str
    model: str
    prompt: str


class RunTrace(BaseModel):
    run_id: str
    case_name: str
    status: RunStatus
    started_at: str
    finished_at: str
    steps: list[StepResult] = []
    assertions: list[AssertionResult] = []
    metrics: RunMetrics = RunMetrics()
    versions: RunVersions
    error: str = ""
