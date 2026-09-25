import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from agentqa import __version__

DEFAULT_BASE_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"
JEV_TIMEOUT_S = 30


class JevAPIError(RuntimeError):
    pass


class JevFormatError(RuntimeError):
    pass


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str]


class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[str, str] | None = None


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str]


JevQuestion = ChoiceQuestion | NoulQuestion | ScoreQuestion


class JevAnswer(BaseModel):
    type: Literal["choice", "noul", "score"]
    choice: str | None = None
    noul: float | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = {}


class JevResult(BaseModel):
    model: str
    answers: dict[str, JevAnswer]
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class JevClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = JEV_TIMEOUT_S,
    ):
        self.model = model
        self.base_url = base_url
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": f"agentqa/{__version__}"},
        )

    @classmethod
    def from_env(cls) -> "JevClient":
        api_key = os.environ.get("AGENTQA_JEV_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("AGENTQA_JEV_API_KEY is required (or set OPENROUTER_API_KEY)")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("AGENTQA_JEV_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("AGENTQA_JEV_MODEL", DEFAULT_MODEL),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def decide(
        self,
        state: str | dict[str, Any],
        questions: dict[str, JevQuestion],
    ) -> JevResult:
        body = {
            "model": self.model,
            "state": state,
            "questions": {
                name: question.model_dump(exclude_none=True) for name, question in questions.items()
            },
        }
        try:
            response = await self._client.post(
                self.base_url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as exc:
            raise JevAPIError(f"Jev request failed: {exc}") from exc
        if response.status_code >= 400:
            raise JevAPIError(
                f"Jev request failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise JevFormatError("response is not valid JSON") from exc
        return self._parse(payload)

    def _parse(self, payload: dict[str, Any]) -> JevResult:
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise JevFormatError(f"response missing answers: {payload!r}")
        try:
            parsed = {name: JevAnswer.model_validate(answer) for name, answer in answers.items()}
        except Exception as exc:
            raise JevFormatError(f"invalid answers payload: {answers!r}") from exc
        usage = payload.get("usage") or {}
        return JevResult(
            model=str(payload.get("model", self.model)),
            answers=parsed,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            cost=float(usage.get("cost", 0.0) or 0.0),
        )
