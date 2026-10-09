from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentqa.contracts.actions import Operation
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    ChoiceAnswer,
    DecisionAnswer,
    DecisionRequest,
    DecisionResult,
    GenerationRequest,
    GenerationResult,
    NoulAnswer,
    ProviderRoute,
    Usage,
)
from agentqa.models.wire import GO_WIRE_VERSION, ModelTransportError

FAKE_GO_MODEL = "deepseek-v4.1-flash"
FAKE_JEV_MODEL = "jev-1.13-free"


class PlanDrivenGo:
    route = ProviderRoute.OPENCODE_GO
    schema_version = GO_WIRE_VERSION

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._steps = list(steps)
        self._index = 0
        self.requests: list[GenerationRequest] = []
        self.emitted: list[dict[str, Any]] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self._index >= len(self._steps):
            return self._result({"decision": "stop", "rationale": "script exhausted"})
        step = self._steps[self._index]
        self._index += 1
        if step.get("error"):
            raise ModelTransportError(
                ErrorCode(str(step["error"])),
                f"scripted provider error {step['error']}",
                retryable=bool(step.get("retryable", False)),
            )
        if step.get("raw") is not None:
            return self._result(dict(step["raw"]))
        operation_name = step.get("operation", "click")
        operation = Operation(operation_name)
        structured: dict[str, Any] = {
            "decision": "action",
            "operation": operation_name,
            "intent": step.get("intent"),
            "confidence": step.get("confidence", 0.9),
            "rationale": step.get("rationale", "scripted"),
        }
        if step.get("value") is not None:
            structured["value"] = step["value"]
        if operation.needs_target():
            match = dict(step.get("match", {}))
            context = _context_from_request(request)
            candidates = context.get("candidates", [])
            candidate = _match_candidate(candidates, match)
            if candidate is None:
                return self._result({"decision": "need_more_context", "rationale": "scripted candidate missing"})
            structured["candidate"] = candidate["candidate_id"]
        return self._result(structured)

    def _result(self, structured: dict[str, Any]) -> GenerationResult:
        self.emitted.append(structured)
        return GenerationResult(
            route=self.route,
            model=FAKE_GO_MODEL,
            model_resolved=FAKE_GO_MODEL,
            raw_text=json.dumps(structured, ensure_ascii=False),
            structured=structured,
            usage=Usage(input_tokens=10, output_tokens=5),
        )


class ScriptedJev:
    route = ProviderRoute.OPENCODE_ZEN
    schema_version = "opencode-zen-systemone/1"

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._steps = list(steps)
        self._index = 0
        self.requests: list[DecisionRequest] = []

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        if self._index >= len(self._steps):
            answers: dict[str, DecisionAnswer] = {}
            return DecisionResult(model=FAKE_JEV_MODEL, answers=answers)
        step = self._steps[self._index]
        self._index += 1
        if step.get("error"):
            raise ModelTransportError(ErrorCode(str(step["error"])), f"scripted error {step['error']}")
        answers: dict[str, DecisionAnswer] = {}
        for question in request.questions:
            if question.question_id == "progress":
                answers["progress"] = NoulAnswer(noul=float(step.get("noul", 0.1)))
            elif question.question_id == "next_action":
                choice = step.get("choice", "none")
                probabilities = {key: 0.0 for key in question.criteria}
                probabilities[choice] = float(step.get("confidence", 0.9))
                remainder = max(0.0, 1.0 - probabilities[choice])
                others = [key for key in question.criteria if key != choice]
                for key in others:
                    probabilities[key] = remainder / len(others) if others else 0.0
                answers["next_action"] = ChoiceAnswer(
                    choice=choice,
                    confidence=float(step.get("confidence", 0.9)),
                    probabilities=probabilities,
                )
        return DecisionResult(model=FAKE_JEV_MODEL, answers=answers, usage=Usage(input_tokens=8, output_tokens=2))


def _context_from_request(request: GenerationRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        for part in message.parts:
            text = getattr(part, "text", None)
            if not text:
                continue
            try:
                payload = json.loads(text)
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            if "candidates" in payload:
                return payload
            observation = payload.get("observation")
            if isinstance(observation, dict) and "candidates" in observation:
                return observation
    return {}


def _match_candidate(candidates: list[dict[str, Any]], match: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in candidates:
        if match.get("role") is not None and candidate.get("role") != match["role"]:
            continue
        if match.get("name") is not None and candidate.get("name") != match["name"]:
            continue
        if not candidate.get("visible", True):
            continue
        if candidate.get("actionability") in ("disabled", "offscreen"):
            continue
        return candidate
    return None


def load_agent_models(script_path: Path):
    from agentqa.platform.runs.composition import AgentModels

    document = json.loads(Path(script_path).read_text(encoding="utf-8"))
    return AgentModels(
        generative=PlanDrivenGo(document.get("go", [])),
        decision=ScriptedJev(document.get("jev", [])),
    )


__all__ = ["PlanDrivenGo", "ScriptedJev", "load_agent_models"]
