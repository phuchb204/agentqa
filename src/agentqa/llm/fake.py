from agentqa.contracts import Action
from agentqa.llm.adapter import LLMResult


class FakeLLM:
    def __init__(self, actions: list[Action], input_tokens: int = 10, output_tokens: int = 5):
        self.model = "fake"
        self._actions = list(actions)
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[str] = []

    async def decide(self, system: str, user: str) -> LLMResult:
        self.calls.append(user)
        if not self._actions:
            raise RuntimeError("FakeLLM has no scripted actions left")
        return LLMResult(
            action=self._actions.pop(0),
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
