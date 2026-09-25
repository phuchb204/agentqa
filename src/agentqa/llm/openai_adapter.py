import json
import os
import re
import uuid
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel

from agentqa import __version__
from agentqa.contracts import Action
from agentqa.llm.adapter import LLMResult

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API = "chat"
API_MODES = ("chat", "responses")


class LLMFormatError(RuntimeError):
    pass


class ActionDecision(BaseModel):
    type: Literal["navigate", "click", "fill", "finish"]
    target: str = ""
    value: str = ""
    rationale: str = ""


def _to_action(decision: ActionDecision) -> Action:
    return Action(
        type=decision.type,
        target=decision.target or None,
        value=decision.value or None,
        rationale=decision.rationale,
    )


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMFormatError(f"no JSON object found in LLM output: {cleaned[:200]!r}")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMFormatError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMFormatError("LLM output JSON is not an object")
    return payload


class OpenAICompatAdapter:
    def __init__(self, *, base_url: str, api_key: str, model: str, api: str = DEFAULT_API):
        if api not in API_MODES:
            raise ValueError(f"unsupported api mode: {api!r} (expected one of {API_MODES})")
        self.model = model
        self.api = api
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers={
                "User-Agent": f"agentqa/{__version__}",
                "x-opencode-session": uuid.uuid4().hex,
            },
        )

    @classmethod
    def from_env(cls) -> "OpenAICompatAdapter":
        base_url = os.environ.get("AGENTQA_LLM_BASE_URL", DEFAULT_BASE_URL)
        api_key = os.environ.get("AGENTQA_LLM_API_KEY", "")
        if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
            raise RuntimeError(
                "AGENTQA_LLM_API_KEY is required (set it in .env; Ollama local does not need one)"
            )
        return cls(
            base_url=base_url,
            api_key=api_key or "not-needed",
            model=os.environ.get("AGENTQA_LLM_MODEL", DEFAULT_MODEL),
            api=os.environ.get("AGENTQA_LLM_API", DEFAULT_API),
        )

    def _to_result(self, content: str, input_tokens: int, output_tokens: int) -> LLMResult:
        payload = _extract_json(content)
        try:
            decision = ActionDecision.model_validate(payload)
        except Exception as exc:
            raise LLMFormatError(f"invalid action payload: {payload!r}") from exc
        return LLMResult(
            action=_to_action(decision),
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
        )

    async def _decide_chat(self, system: str, user: str) -> LLMResult:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        return self._to_result(
            content,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    async def _decide_responses(self, system: str, user: str) -> LLMResult:
        response = await self._client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
        )
        usage = response.usage
        return self._to_result(
            response.output_text or "",
            getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0,
        )

    async def decide(self, system: str, user: str) -> LLMResult:
        if self.api == "responses":
            return await self._decide_responses(system, user)
        return await self._decide_chat(system, user)
