from __future__ import annotations

import httpx

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionRequest,
    DecisionResult,
    NoulAnswer,
    NoulQuestion,
    ProviderRoute,
    ScoreAnswer,
    ScoreQuestion,
)
from agentqa.contracts.ports import CallLedgerPort
from agentqa.contracts.values import JsonValue, SensitiveValue
from agentqa.models.retry import RetryController, TransportReply
from agentqa.models.usage import AttemptLedger, parse_zen_usage
from agentqa.models.wire import (
    ZEN_WIRE_VERSION,
    ModelTransportError,
    authorization_header,
    classify_http_status,
    ensured_url,
    parse_json_object,
    user_agent,
)

PROBABILITY_EPSILON = 1e-9


class ZenSystemOneAdapter:
    route = ProviderRoute.OPENCODE_ZEN
    schema_version = ZEN_WIRE_VERSION

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: SensitiveValue,
        client: httpx.AsyncClient | None = None,
        retry: RetryController | None = None,
        ledger: CallLedgerPort | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._url = ensured_url(self.route, base_url)
        self._model = model
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._retry = retry or RetryController()
        self._ledger = ledger

    async def aclose(self) -> None:
        await self._client.aclose()

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        attempt_ledger = AttemptLedger(
            route=self.route,
            requested_model=self._model,
        )

        def record(attempt) -> None:
            attempt_ledger.record_attempt(self._ledger, attempt)

        result = await self._retry.run(lambda attempt_no: self._attempt(request, attempt_no), record_attempt=record)
        return result.value

    async def _attempt(self, request: DecisionRequest, attempt_no: int) -> TransportReply[DecisionResult]:
        body = self._build_body(request)
        headers = self._headers()
        try:
            response = await self._client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as error:
            raise ModelTransportError(
                ErrorCode.PROVIDER_TIMEOUT, "Zen request quá thời gian", retryable=True
            ) from error
        except httpx.HTTPError as error:
            raise ModelTransportError(ErrorCode.PROVIDER_TIMEOUT, "Zen transport lỗi", retryable=True) from error
        if response.status_code >= 300:
            raise classify_http_status(response.status_code, headers=response.headers)
        payload = parse_json_object(response.text)
        result = self._parse_result(payload, request)
        return TransportReply(value=result, usage=result.usage, resolved_model=result.model)

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": authorization_header(self._api_key.reveal()),
            "content-type": "application/json",
            "user-agent": user_agent(),
        }

    def _build_body(self, request: DecisionRequest) -> dict[str, JsonValue]:
        questions: dict[str, JsonValue] = {}
        for question in request.questions:
            if isinstance(question, ChoiceQuestion):
                if not question.criteria:
                    raise ModelTransportError(
                        ErrorCode.INPUT_INVALID, f"Choice question '{question.question_id}' thiếu criteria"
                    )
                questions[question.question_id] = {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": dict(question.criteria),
                }
            elif isinstance(question, NoulQuestion):
                questions[question.question_id] = {
                    "type": "noul",
                    "instructions": question.instructions,
                }
            elif isinstance(question, ScoreQuestion):
                if not question.criteria:
                    raise ModelTransportError(
                        ErrorCode.INPUT_INVALID, f"Score question '{question.question_id}' thiếu criteria"
                    )
                questions[question.question_id] = {
                    "type": "score",
                    "instructions": question.instructions,
                    "criteria": list(question.criteria),
                }
            else:
                raise ModelTransportError(ErrorCode.INPUT_INVALID, "Question type không hỗ trợ")
        return {"model": self._model, "state": request.state, "questions": questions}

    def _parse_result(self, payload: dict[str, JsonValue], request: DecisionRequest) -> DecisionResult:
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen response thiếu answers dạng object")
        requested = {question.question_id: question for question in request.questions}
        if set(raw_answers) != set(requested):
            missing = sorted(set(requested) - set(raw_answers))
            unknown = sorted(set(raw_answers) - set(requested))
            raise ModelTransportError(
                ErrorCode.PROVIDER_SCHEMA,
                f"Zen answers không khớp question IDs (missing={missing}, unknown={unknown})",
            )
        answers: dict[str, DecisionAnswer] = {}
        for question_id, question in requested.items():
            answers[question_id] = _validate_answer(question, raw_answers[question_id])
        model = payload.get("model") if isinstance(payload.get("model"), str) else None
        return DecisionResult(model=model, answers=answers, usage=parse_zen_usage(payload.get("usage")))


def _validate_answer(question: ChoiceQuestion | NoulQuestion | ScoreQuestion, raw: object) -> DecisionAnswer:
    if not isinstance(raw, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen answer phải là object")
    answer_type = raw.get("type")
    kind = question.kind.value
    if answer_type != kind:
        raise ModelTransportError(
            ErrorCode.PROVIDER_SCHEMA,
            f"Zen answer type '{answer_type}' không khớp question type '{kind}'",
        )
    if isinstance(question, ChoiceQuestion):
        choice = raw.get("choice")
        if not isinstance(choice, str) or choice not in question.criteria:
            raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen choice không thuộc criteria")
        confidence = _probability(("confidence",), raw.get("confidence"))
        probabilities = _probabilities(raw.get("probabilities"))
        if set(probabilities) != set(question.criteria):
            raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen probabilities không khớp criteria")
        return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities)
    if isinstance(question, NoulQuestion):
        return NoulAnswer(noul=_probability(("noul",), raw.get("noul")))
    score = _finite(("score",), raw.get("score"))
    levels = len(question.criteria)
    if score < -PROBABILITY_EPSILON or score > levels - 1 + PROBABILITY_EPSILON:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen score ngoài khoảng criteria")
    confidence = _probability(("confidence",), raw.get("confidence"))
    legend = raw.get("legend")
    if not isinstance(legend, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen score thiếu legend")
    probabilities = _probabilities(raw.get("probabilities"))
    if not set(probabilities) <= set(legend):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Zen probabilities không khớp legend")
    return ScoreAnswer(score=score, confidence=confidence, legend=dict(legend), probabilities=probabilities)


def _finite(path: tuple[str | int, ...], value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, f"Giá trị tại {'/'.join(map(str, path))} không phải số")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Giá trị không hữu hạn")
    return number


def _probability(path: tuple[str | int, ...], value: object) -> float:
    number = _finite(path, value)
    if number < -PROBABILITY_EPSILON or number > 1 + PROBABILITY_EPSILON:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Xác suất ngoài [0, 1]")
    return number


def _probabilities(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "probabilities phải là object")
    return {str(key): _probability(("probabilities", str(key)), item) for key, item in value.items()}
