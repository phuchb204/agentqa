from typing import Protocol

from pydantic import BaseModel

from agentqa.contracts import Action


class LLMResult(BaseModel):
    action: Action
    input_tokens: int = 0
    output_tokens: int = 0


class LLMAdapter(Protocol):
    model: str

    async def decide(self, system: str, user: str) -> LLMResult: ...
