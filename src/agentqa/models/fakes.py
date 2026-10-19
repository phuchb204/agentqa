from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    DecisionAnswer,
    DecisionRequest,
    DecisionResult,
    GenerationRequest,
    GenerationResult,
    MessagePurpose,
    OutputFormat,
    ProviderRoute,
    Usage,
)
from agentqa.contracts.ports import CallLedgerPort
from agentqa.contracts.values import JsonValue
from agentqa.models.usage import AttemptLedger
from agentqa.models.wire import (
    GO_WIRE_VERSION,
    ZEN_WIRE_VERSION,
    CallAttempt,
    ModelTransportError,
    parse_json_object,
)

FAKE_GO_MODEL = "deepseek-v4.1-flash"
FAKE_JEV_MODEL = "jev-1.13-free"


@dataclass
class ScriptedGoReply:
    text: str = "ok"
    structured: dict[str, JsonValue] | None = None
    usage: Usage | None = None
    model_resolved: str | None = None
    error: ErrorCode | None = None
    retryable: bool = False


class FakeGo:
    route = ProviderRoute.OPENCODE_GO
    schema_version = GO_WIRE_VERSION

    def __init__(
        self,
        replies: ScriptedGoReply | list[ScriptedGoReply] | None = None,
        *,
        model: str = FAKE_GO_MODEL,
        ledger: CallLedgerPort | None = None,
        route: ProviderRoute | None = None,
    ) -> None:
        if replies is None:
            replies = [ScriptedGoReply()]
        self._replies = list(replies) if isinstance(replies, list) else [replies]
        self._model = model
        self._ledger = ledger
        if route is not None:
            self.route = route
        self.requests: list[GenerationRequest] = []
        self.attempts: list[CallAttempt] = []

    @property
    def remaining(self) -> int:
        return len(self._replies)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        reply = self._replies.pop(0) if self._replies else ScriptedGoReply()
        attempt_ledger = AttemptLedger(
            purpose=request.purpose,
            route=self.route,
            requested_model=self._model,
        )
        attempt = CallAttempt(
            attempt=1,
            started_at=_utc_now(),
            ended_at=_utc_now(),
            outcome=_outcome_for(reply.error),
            usage=reply.usage,
            error_code=reply.error,
            resolved_model=reply.model_resolved,
        )
        self.attempts.append(attempt)
        attempt_ledger.record_attempt(self._ledger, attempt)
        if reply.error is not None:
            raise ModelTransportError(reply.error, f"FakeGo error {reply.error.value}", retryable=reply.retryable)
        structured = reply.structured
        if structured is None and request.output_format == OutputFormat.JSON_OBJECT and reply.text:
            try:
                structured = parse_json_object(reply.text)
            except ModelTransportError:
                structured = None
        return GenerationResult(
            route=self.route,
            model=self._model,
            model_resolved=reply.model_resolved or self._model,
            raw_text=reply.text,
            structured=structured,
            usage=reply.usage,
        )


@dataclass
class ScriptedJevReply:
    answers: dict[str, DecisionAnswer] | None = None
    usage: Usage | None = None
    model: str | None = None
    error: ErrorCode | None = None
    retryable: bool = False


class FakeJev:
    route = ProviderRoute.OPENCODE_ZEN
    schema_version = ZEN_WIRE_VERSION

    def __init__(
        self,
        replies: ScriptedJevReply | list[ScriptedJevReply] | None = None,
        *,
        model: str = FAKE_JEV_MODEL,
        ledger: CallLedgerPort | None = None,
        route: ProviderRoute | None = None,
    ) -> None:
        if replies is None:
            replies = [ScriptedJevReply()]
        self._replies = list(replies) if isinstance(replies, list) else [replies]
        self._model = model
        self._ledger = ledger
        if route is not None:
            self.route = route
        self.requests: list[DecisionRequest] = []
        self.attempts: list[CallAttempt] = []

    @property
    def remaining(self) -> int:
        return len(self._replies)

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        reply = self._replies.pop(0) if self._replies else ScriptedJevReply()
        attempt_ledger = AttemptLedger(
            purpose=MessagePurpose.DECIDE,
            route=self.route,
            requested_model=self._model,
        )
        attempt = CallAttempt(
            attempt=1,
            started_at=_utc_now(),
            ended_at=_utc_now(),
            outcome=_outcome_for(reply.error),
            usage=reply.usage,
            error_code=reply.error,
            resolved_model=reply.model,
        )
        self.attempts.append(attempt)
        attempt_ledger.record_attempt(self._ledger, attempt)
        if reply.error is not None:
            raise ModelTransportError(reply.error, f"FakeJev error {reply.error.value}", retryable=reply.retryable)
        return DecisionResult(
            model=reply.model or self._model,
            answers=dict(reply.answers or {}),
            usage=reply.usage,
        )


@dataclass
class ScriptedHttp:
    status: int = 200
    json_payload: Any = None
    text: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    raise_timeout: bool = False
    raise_connect: bool = False


class HttpRecorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[Any] = []

    @property
    def count(self) -> int:
        return len(self.requests)

    def transport(self, script: list[ScriptedHttp]) -> httpx.MockTransport:
        pending = list(script)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            import json as json_module

            self.bodies.append(json_module.loads(request.content.decode("utf-8")) if request.content else None)
            if not pending:
                raise AssertionError("HTTP script đã hết nhưng vẫn có request mới")
            item = pending.pop(0)
            if item.raise_timeout:
                raise httpx.TimeoutException("scripted timeout", request=request)
            if item.raise_connect:
                raise httpx.ConnectError("scripted connect error", request=request)
            if item.text is not None:
                return httpx.Response(item.status, text=item.text, headers=item.headers)
            return httpx.Response(item.status, json=item.json_payload, headers=item.headers)

        return httpx.MockTransport(handler)


def _utc_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _outcome_for(error: ErrorCode | None):
    from agentqa.contracts.models import ModelCallOutcome

    if error is None:
        return ModelCallOutcome.SUCCEEDED
    return ModelCallOutcome.FAILED
