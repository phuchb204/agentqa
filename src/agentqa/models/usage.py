from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from agentqa.contracts.models import (
    MessagePurpose,
    ModelCallOutcome,
    ModelCallRecord,
    ProviderRoute,
    Usage,
)
from agentqa.contracts.ports import CallLedgerPort
from agentqa.models.wire import CallAttempt


@dataclass(frozen=True)
class UsageTotals:
    calls: int
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    missing_usage_calls: int
    unknown_calls: int
    state: str


class CallLedger:
    def __init__(self) -> None:
        self.records: list[ModelCallRecord] = []

    def record(self, call: ModelCallRecord) -> UUID:
        self.records.append(call)
        return call.call_id

    def calls(self, group_id: UUID) -> list[ModelCallRecord]:
        return [record for record in self.records if record.group_id == group_id]

    def totals(self) -> UsageTotals:
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        reported_input = False
        reported_output = False
        reported_cached = False
        missing_usage = 0
        unknown_calls = 0
        for record in self.records:
            if record.outcome is ModelCallOutcome.UNKNOWN:
                unknown_calls += 1
            if record.usage is None:
                missing_usage += 1
                continue
            if record.usage.input_tokens is not None:
                input_tokens += record.usage.input_tokens
                reported_input = True
            if record.usage.output_tokens is not None:
                output_tokens += record.usage.output_tokens
                reported_output = True
            if record.usage.cached_tokens is not None:
                cached_tokens += record.usage.cached_tokens
                reported_cached = True
        if missing_usage and not any((reported_input, reported_output, reported_cached)):
            state = "unknown"
        elif missing_usage or unknown_calls:
            state = "partial"
        else:
            state = "complete"
        return UsageTotals(
            calls=len(self.records),
            attempts=len(self.records),
            input_tokens=input_tokens if reported_input else None,
            output_tokens=output_tokens if reported_output else None,
            cached_tokens=cached_tokens if reported_cached else None,
            missing_usage_calls=missing_usage,
            unknown_calls=unknown_calls,
            state=state,
        )


@dataclass
class AttemptLedger:
    purpose: MessagePurpose = MessagePurpose.DECIDE
    route: ProviderRoute = ProviderRoute.OPENCODE_GO
    requested_model: str = ""
    session_id: str | None = None
    group_id: UUID = field(default_factory=uuid4)
    call_ids: list[UUID] = field(default_factory=list)

    def record_attempt(self, ledger: CallLedgerPort | None, attempt: CallAttempt) -> ModelCallRecord:
        call = ModelCallRecord(
            call_id=uuid4(),
            group_id=self.group_id,
            attempt=attempt.attempt,
            purpose=self.purpose,
            requested_model=self.requested_model,
            resolved_model=attempt.resolved_model,
            route=self.route,
            session_id=self.session_id,
            usage=attempt.usage,
            outcome=attempt.outcome,
            error_code=attempt.error_code,
            started_at=attempt.started_at,
            ended_at=attempt.ended_at,
        )
        self.call_ids.append(call.call_id)
        if ledger is not None:
            ledger.record(call)
        return call


def usage_totals(records: list[ModelCallRecord]) -> UsageTotals:
    ledger = CallLedger()
    for record in records:
        ledger.record(record)
    return ledger.totals()


def parse_provider_usage(payload: object) -> Usage | None:
    if not isinstance(payload, dict):
        return None
    input_tokens = _as_token(payload.get("prompt_tokens"))
    output_tokens = _as_token(payload.get("completion_tokens"))
    if input_tokens is None:
        input_tokens = _as_token(payload.get("input_tokens"))
    if output_tokens is None:
        output_tokens = _as_token(payload.get("output_tokens"))
    cached_tokens = None
    details = payload.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached_tokens = _as_token(details.get("cached_tokens"))
    if cached_tokens is None:
        cached_tokens = _as_token(payload.get("cached_tokens"))
    if input_tokens is None and output_tokens is None and cached_tokens is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached_tokens)


def _as_token(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def parse_zen_usage(payload: object) -> Usage | None:
    if not isinstance(payload, dict):
        return None
    input_tokens = _as_token(payload.get("input_tokens"))
    output_tokens = _as_token(payload.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=None)


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
