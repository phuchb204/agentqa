from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agentqa.agent.history import ActionHistory
from agentqa.agent.planning.planner import PlanningPlan
from agentqa.agent.planning.runner import AgentObservation
from agentqa.contracts.actions import Operation
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    OutputFormat,
)
from agentqa.contracts.policies import (
    AgentProposal,
    PolicyKind,
    PolicyOutcome,
    PolicyProfile,
    ProposalKind,
)
from agentqa.contracts.ports import GenerativeModelPort
from agentqa.contracts.values import CaptureValue, LiteralValue, ParameterValue, ValueExpr
from agentqa.models.wire import ModelTransportError

MAX_RATIONALE = 240
ALLOWED_VALUE_KINDS = ("literal", "parameter", "capture")


class ProposalParseError(RuntimeError):
    def __init__(self, code: ErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class ParsedDecision:
    decision: str
    operation: str | None
    candidate_id: str | None
    intent: str | None
    value_expr: ValueExpr | None
    confidence: float | None
    progress: float | None
    rationale: str


def parse_agent_decision(payload: dict[str, Any]) -> ParsedDecision:
    if not isinstance(payload, dict):
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "Payload không phải object")
    decision = payload.get("decision")
    if decision not in ("action", "stop", "need_more_context"):
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, f"decision không hợp lệ: {decision!r}")
    rationale = payload.get("rationale", "")
    if not isinstance(rationale, str):
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "rationale phải là chuỗi")
    rationale = rationale.strip()[:MAX_RATIONALE]
    confidence = _optional_ratio(payload.get("confidence"), "confidence")
    progress = _optional_ratio(payload.get("progress"), "progress")
    operation = payload.get("operation")
    candidate_id = payload.get("candidate")
    intent = payload.get("intent")
    value_expr = _parse_value(payload.get("value"))
    if decision == "action":
        if not isinstance(operation, str) or operation not in {item.value for item in Operation}:
            raise ProposalParseError(ErrorCode.UNKNOWN_OPERATION, f"operation không thuộc registry: {operation!r}")
        if candidate_id is not None and not (isinstance(candidate_id, str) and candidate_id.startswith("c")):
            raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, f"candidate không hợp lệ: {candidate_id!r}")
        if intent is not None and not isinstance(intent, str):
            raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "intent phải là chuỗi")
    else:
        operation = None if decision != "stop" else operation
        candidate_id = None
        intent = None
        value_expr = None
    return ParsedDecision(
        decision=decision,
        operation=operation if isinstance(operation, str) else None,
        candidate_id=candidate_id if isinstance(candidate_id, str) else None,
        intent=intent if isinstance(intent, str) else None,
        value_expr=value_expr,
        confidence=confidence,
        progress=progress,
        rationale=rationale,
    )


def _optional_ratio(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, f"{name} phải là số")
    number = float(value)
    if number != number or number < 0 or number > 1:
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, f"{name} ngoài [0, 1]")
    return number


def _parse_value(raw: object) -> ValueExpr | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "value phải là object")
    kind = raw.get("kind")
    if kind not in ALLOWED_VALUE_KINDS:
        raise ProposalParseError(ErrorCode.SECRET_INTERPOLATION, f"value kind không được phép: {kind!r}")
    if kind == "literal":
        return LiteralValue(kind="literal", value=raw.get("value"))
    if kind == "parameter":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "parameter.value thiếu name")
        return ParameterValue(kind="parameter", name=name)
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "capture.value thiếu name")
    return CaptureValue(kind="capture", name=name)


class LLMPolicy:
    def __init__(
        self,
        model: GenerativeModelPort,
        *,
        profile: PolicyProfile,
        max_repair: int = 1,
    ) -> None:
        self._model = model
        self._profile = profile
        self._max_repair = max_repair

    async def propose(
        self,
        *,
        observation: AgentObservation,
        plan: PlanningPlan,
        history: ActionHistory,
    ) -> PolicyOutcome:
        request = self._build_request(observation, plan, history)
        try:
            result = await self._model.generate(request)
        except ModelTransportError as error:
            return PolicyOutcome(
                kind=ProposalKind.FAILED,
                reason=f"provider:{error.code.value}",
                detail=str(error),
                policy_version=self._profile.version,
            )
        raw_text = result.raw_text or ""
        try:
            parsed = self._parse(result.structured, raw_text)
        except ProposalParseError as first_error:
            repaired = await self._repair(request, raw_text, first_error)
            if isinstance(repaired, PolicyOutcome):
                return repaired
            parsed = repaired
        return self._to_outcome(parsed, observation)

    def _parse(self, structured: dict | None, raw_text: str) -> ParsedDecision:
        if structured is None:
            raise ProposalParseError(ErrorCode.PROVIDER_SCHEMA, "Model không trả JSON object")
        return parse_agent_decision(structured)

    async def _repair(
        self,
        request: GenerationRequest,
        raw_text: str,
        error: ProposalParseError,
    ) -> ParsedDecision | PolicyOutcome:
        if self._max_repair < 1:
            return PolicyOutcome(
                kind=ProposalKind.MALFORMED,
                reason="parse_failed",
                detail=error.detail,
                policy_version=self._profile.version,
            )
        repair_request = request.model_copy(
            update={
                "purpose": MessagePurpose.REPAIR,
                "messages": [
                    *request.messages,
                    GenerationMessage(
                        role=GenerationMessageRole.ASSISTANT,
                        parts=[GenerationTextPart(text=raw_text[:2000])],
                    ),
                    GenerationMessage(
                        role=GenerationMessageRole.USER,
                        parts=[
                            GenerationTextPart(
                                text=(
                                    "Output trước không hợp lệ: "
                                    f"{error.detail}. Trả lại đúng một JSON object theo schema đã cho."
                                )
                            )
                        ],
                    ),
                ],
            }
        )
        try:
            repaired = await self._model.generate(repair_request)
        except ModelTransportError as transport_error:
            return PolicyOutcome(
                kind=ProposalKind.FAILED,
                reason=f"provider:{transport_error.code.value}",
                detail=str(transport_error),
                policy_version=self._profile.version,
            )
        try:
            return self._parse(repaired.structured, repaired.raw_text or "")
        except ProposalParseError as second_error:
            return PolicyOutcome(
                kind=ProposalKind.MALFORMED,
                reason="repair_failed",
                detail=second_error.detail,
                policy_version=self._profile.version,
            )

    def _to_outcome(self, parsed: ParsedDecision, observation: AgentObservation) -> PolicyOutcome:
        if parsed.decision == "stop":
            return PolicyOutcome(
                kind=ProposalKind.STOP,
                reason="llm_stop",
                detail=parsed.rationale or "model đề xuất dừng",
                policy_version=self._profile.version,
            )
        if parsed.decision == "need_more_context":
            return PolicyOutcome(
                kind=ProposalKind.NEED_CONTEXT,
                reason="llm_need_more_context",
                detail=parsed.rationale,
                policy_version=self._profile.version,
            )
        operation = Operation(parsed.operation)
        if operation.needs_target() and parsed.candidate_id is None:
            return PolicyOutcome(
                kind=ProposalKind.MALFORMED,
                reason="missing_candidate",
                detail=f"{operation.value} cần target candidate",
                policy_version=self._profile.version,
            )
        candidate = None
        if parsed.candidate_id is not None:
            candidate = next(
                (item for item in observation.candidates if item.candidate_id == parsed.candidate_id),
                None,
            )
            if candidate is None:
                return PolicyOutcome(
                    kind=ProposalKind.FAILED,
                    reason="guard_rejected:candidate_unknown",
                    detail=parsed.candidate_id,
                    policy_version=self._profile.version,
                )
            if not candidate.visible or candidate.actionability.value == "disabled":
                return PolicyOutcome(
                    kind=ProposalKind.FAILED,
                    reason="guard_rejected:candidate_not_actionable",
                    detail=parsed.candidate_id,
                    policy_version=self._profile.version,
                )
        if parsed.confidence is not None and parsed.confidence < self._profile.confidence_min:
            return PolicyOutcome(
                kind=ProposalKind.LOW_CONFIDENCE,
                reason="below_threshold",
                detail=f"confidence={parsed.confidence}",
                policy_version=self._profile.version,
            )
        proposal = AgentProposal(
            proposal_id=uuid4(),
            policy=PolicyKind.LLM,
            policy_version=self._profile.version,
            plan_version="",
            operation=operation,
            target_intent=parsed.intent or (candidate.name if candidate else None),
            candidate_id=parsed.candidate_id,
            value=parsed.value_expr,
            rationale=parsed.rationale,
            confidence=parsed.confidence,
            progress=parsed.progress,
        )
        return PolicyOutcome(kind=ProposalKind.ACTION, proposal=proposal, policy_version=self._profile.version)

    def _build_request(
        self,
        observation: AgentObservation,
        plan: PlanningPlan,
        history: ActionHistory,
    ) -> GenerationRequest:
        context = {
            "goal": plan.goal,
            "plan_version": plan.version,
            "subgoals": [
                {
                    "id": subgoal.subgoal_id,
                    "goal": subgoal.goal,
                    "requirements": list(subgoal.requirement_refs),
                }
                for subgoal in plan.subgoals
            ],
            "observation": observation.payload,
            "history": history.summary(),
            "allowed_operations": sorted(
                item.value for item in Operation if item.needs_target() or item is Operation.NAVIGATE
            ),
            "response_schema": {
                "decision": "action | stop | need_more_context",
                "operation": "tên operation trong registry khi decision=action",
                "candidate": "candidate_id từ observation, bắt buộc với operation cần target",
                "value": {"kind": "literal | parameter | capture", "value": "giá trị hoặc name"},
                "confidence": "0..1",
                "progress": "0..1",
                "rationale": "tóm tắt ngắn, không suy nghĩ nội bộ",
            },
        }
        return GenerationRequest(
            purpose=MessagePurpose.PROPOSE,
            schema_name="agent_decision",
            schema_version="1",
            prompt_ref=f"policy://llm/{self._profile.version}",
            output_format=OutputFormat.JSON_OBJECT,
            messages=[
                GenerationMessage(
                    role=GenerationMessageRole.SYSTEM,
                    parts=[
                        GenerationTextPart(
                            text=(
                                "Bạn là policy chọn action cho browser agent. "
                                "Chỉ trả một JSON object theo response_schema; không giải thích ngoài JSON. "
                                "Không được yêu cầu chạy code hay tool ngoài registry."
                            )
                        )
                    ],
                ),
                GenerationMessage(
                    role=GenerationMessageRole.USER,
                    parts=[GenerationTextPart(text=json.dumps(context, ensure_ascii=False))],
                ),
            ],
        )


__all__ = ["LLMPolicy", "ParsedDecision", "ProposalParseError", "parse_agent_decision"]
