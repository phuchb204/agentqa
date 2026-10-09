from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentqa.contracts.models import (
    MessagePurpose,
    ModelCallOutcome,
    ModelCallRecord,
    ProviderRoute,
    Usage,
)
from agentqa.models.fakes import FakeGo, FakeJev, ScriptedGoReply, ScriptedJevReply
from agentqa.models.usage import (
    AttemptLedger,
    CallLedger,
    parse_provider_usage,
    parse_zen_usage,
)
from agentqa.models.wire import CallAttempt


def call(
    *,
    group: str,
    attempt: int = 1,
    usage: Usage | None,
    outcome: ModelCallOutcome = ModelCallOutcome.SUCCEEDED,
    purpose: MessagePurpose = MessagePurpose.DECIDE,
) -> ModelCallRecord:
    from uuid import UUID

    return ModelCallRecord(
        call_id=UUID(int=hash((group, attempt)) % (2**128)),
        group_id=UUID(int=hash(group) % (2**128)),
        attempt=attempt,
        purpose=purpose,
        requested_model="deepseek-v4.1-flash",
        route=ProviderRoute.OPENCODE_GO,
        usage=usage,
        outcome=outcome,
        started_at=datetime(2026, 10, 9, tzinfo=UTC),
        ended_at=datetime(2026, 10, 9, tzinfo=UTC),
    )


def test_totals_for_retry_finish_and_parallel_calls() -> None:
    ledger = CallLedger()
    ledger.record(call(group="retry", attempt=1, usage=None, outcome=ModelCallOutcome.UNKNOWN))
    ledger.record(call(group="retry", attempt=2, usage=Usage(input_tokens=100, output_tokens=10)))
    ledger.record(call(group="finish", usage=Usage(input_tokens=50, output_tokens=5)))
    ledger.record(call(group="parallel", usage=Usage(input_tokens=20, output_tokens=2, cached_tokens=7)))
    totals = ledger.totals()
    assert totals.calls == 4
    assert totals.input_tokens == 170
    assert totals.output_tokens == 17
    assert totals.cached_tokens == 7
    assert totals.missing_usage_calls == 1
    assert totals.unknown_calls == 1
    assert totals.state == "partial"


def test_all_reported_is_complete() -> None:
    ledger = CallLedger()
    ledger.record(call(group="a", usage=Usage(input_tokens=1, output_tokens=1)))
    ledger.record(call(group="b", usage=Usage(input_tokens=2, output_tokens=2)))
    totals = ledger.totals()
    assert totals.state == "complete"
    assert totals.missing_usage_calls == 0
    assert totals.input_tokens == 3


def test_zero_tokens_reported_is_not_missing() -> None:
    ledger = CallLedger()
    ledger.record(call(group="free", usage=Usage(input_tokens=0, output_tokens=0)))
    totals = ledger.totals()
    assert totals.state == "complete"
    assert totals.missing_usage_calls == 0
    assert totals.input_tokens == 0
    assert totals.output_tokens == 0
    assert totals.cached_tokens is None


def test_all_missing_is_unknown_not_zero() -> None:
    ledger = CallLedger()
    ledger.record(call(group="a", usage=None))
    ledger.record(call(group="b", usage=None))
    totals = ledger.totals()
    assert totals.state == "unknown"
    assert totals.input_tokens is None
    assert totals.output_tokens is None
    assert totals.missing_usage_calls == 2


def test_attempt_ledger_shares_group_and_numbers_attempts() -> None:
    ledger = CallLedger()
    attempt_ledger = AttemptLedger(purpose=MessagePurpose.DECIDE, requested_model="deepseek-v4.1-flash")
    for number in (1, 2):
        attempt_ledger.record_attempt(
            ledger,
            CallAttempt(
                attempt=number,
                started_at=datetime(2026, 10, 9, tzinfo=UTC),
                ended_at=datetime(2026, 10, 9, tzinfo=UTC),
                outcome=ModelCallOutcome.SUCCEEDED,
                usage=Usage(input_tokens=3),
            ),
        )
    assert len(ledger.records) == 2
    assert {record.group_id for record in ledger.records} == {attempt_ledger.group_id}
    assert [record.attempt for record in ledger.records] == [1, 2]


def test_parse_provider_usage_variants() -> None:
    openai_style = {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "prompt_tokens_details": {"cached_tokens": 4},
    }
    parsed = parse_provider_usage(openai_style)
    assert parsed is not None
    assert (parsed.input_tokens, parsed.output_tokens, parsed.cached_tokens) == (10, 2, 4)
    alternative = parse_provider_usage({"input_tokens": 5, "output_tokens": 1, "cached_tokens": 0})
    assert alternative is not None
    assert (alternative.input_tokens, alternative.output_tokens, alternative.cached_tokens) == (5, 1, 0)
    assert parse_provider_usage({"prompt_tokens": -3}) is None
    assert parse_provider_usage("not-a-dict") is None
    assert parse_provider_usage({}) is None


def test_parse_zen_usage() -> None:
    parsed = parse_zen_usage({"input_tokens": 120, "output_tokens": 12})
    assert parsed is not None
    assert parsed.input_tokens == 120
    assert parsed.output_tokens == 12
    assert parsed.cached_tokens is None
    assert parse_zen_usage({}) is None
    assert parse_zen_usage(None) is None


@pytest.mark.asyncio
async def test_fake_go_records_typed_attempts_and_missing_usage() -> None:
    from agentqa.contracts.models import GenerationRequest, OutputFormat

    ledger = CallLedger()
    fake = FakeGo(
        [
            ScriptedGoReply(text="ok", usage=None),
            ScriptedGoReply(text="ok2", usage=Usage(input_tokens=5, output_tokens=1)),
        ],
        ledger=ledger,
    )
    request = GenerationRequest(
        purpose=MessagePurpose.DECIDE,
        schema_name="policy",
        schema_version="1",
        prompt_ref="prompt://1",
        output_format=OutputFormat.TEXT,
    )
    first = await fake.generate(request)
    second = await fake.generate(request)
    assert first.usage is None
    assert second.usage is not None
    assert len(fake.requests) == 2
    totals = ledger.totals()
    assert totals.calls == 2
    assert totals.state == "partial"
    assert totals.missing_usage_calls == 1
    assert totals.input_tokens == 5


@pytest.mark.asyncio
async def test_fake_jev_returns_scripted_answers() -> None:
    from agentqa.contracts.models import ChoiceAnswer, ChoiceQuestion, DecisionRequest

    fake = FakeJev(
        ScriptedJevReply(
            answers={
                "next_action": ChoiceAnswer(choice="click_login", confidence=0.9, probabilities={"click_login": 1.0})
            },
            usage=Usage(input_tokens=9, output_tokens=1),
        )
    )
    result = await fake.decide(
        DecisionRequest(
            state="x",
            questions=[
                ChoiceQuestion(question_id="next_action", instructions="Chọn", criteria={"click_login": "Đăng nhập"})
            ],
        )
    )
    assert isinstance(result.answers["next_action"], ChoiceAnswer)
    assert result.usage is not None
    assert result.usage.input_tokens == 9
