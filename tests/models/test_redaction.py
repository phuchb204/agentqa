from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    OutputFormat,
    Usage,
)
from agentqa.contracts.values import SensitiveValue
from agentqa.models.fakes import FakeJev, HttpRecorder, ScriptedHttp, ScriptedJevReply
from agentqa.models.opencode_go import GoChatAdapter
from agentqa.models.opencode_zen import ZenSystemOneAdapter
from agentqa.models.retry import RetryController, RetryPolicy
from agentqa.models.usage import CallLedger
from agentqa.models.wire import classify_http_status

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "models"
GO_BASE = "https://opencode.ai/zen/go/v1"
ZEN_BASE = "https://opencode.ai/zen/v1"
CANARY = "sk-canary-secret-do-not-log"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def go_request() -> GenerationRequest:
    return GenerationRequest(
        purpose=MessagePurpose.DECIDE,
        schema_name="policy",
        schema_version="1",
        prompt_ref="prompt://1",
        output_format=OutputFormat.TEXT,
        messages=[GenerationMessage(role=GenerationMessageRole.USER, parts=[GenerationTextPart(text="bước kế tiếp")])],
    )


@pytest.mark.asyncio
async def test_go_key_only_in_authorization_header() -> None:
    recorder = HttpRecorder()
    client = httpx.AsyncClient(transport=recorder.transport([ScriptedHttp(401)]), follow_redirects=False)
    ledger = CallLedger()
    adapter = GoChatAdapter(
        base_url=GO_BASE,
        model="deepseek-v4.1-flash",
        api_key=SensitiveValue(CANARY),
        session_id="conv-1",
        client=client,
        ledger=ledger,
        retry=RetryController(RetryPolicy(max_attempts=1)),
    )
    with pytest.raises(Exception) as excinfo:
        await adapter.generate(go_request())
    assert CANARY not in str(excinfo.value)
    assert CANARY not in json.dumps(recorder.bodies)
    assert recorder.requests[0].headers["authorization"] == f"Bearer {CANARY}"
    serialized = json.dumps([record.model_dump(mode="json") for record in ledger.records])
    assert CANARY not in serialized
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_key_not_in_body_or_error() -> None:
    recorder = HttpRecorder()
    client = httpx.AsyncClient(transport=recorder.transport([ScriptedHttp(402)]), follow_redirects=False)
    adapter = ZenSystemOneAdapter(
        base_url=ZEN_BASE,
        model="jev-1.13-free",
        api_key=SensitiveValue(CANARY),
        client=client,
    )
    from agentqa.contracts.models import DecisionRequest, NoulQuestion

    with pytest.raises(Exception) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[NoulQuestion(question_id="q", instructions="x?")]))
    assert CANARY not in str(excinfo.value)
    assert CANARY not in json.dumps(recorder.bodies)
    assert recorder.requests[0].headers["authorization"] == f"Bearer {CANARY}"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_sdk_convenience_text_field_is_not_wire() -> None:
    recorder = HttpRecorder()
    client = httpx.AsyncClient(
        transport=recorder.transport(
            [ScriptedHttp(200, json_payload={"model": "m", "text": "convenience field", "usage": None})]
        ),
        follow_redirects=False,
    )
    adapter = GoChatAdapter(
        base_url=GO_BASE,
        model="deepseek-v4.1-flash",
        api_key=SensitiveValue("sk-synthetic"),
        session_id="conv-1",
        client=client,
        retry=RetryController(RetryPolicy(max_attempts=1)),
    )
    with pytest.raises(Exception) as excinfo:
        await adapter.generate(go_request())
    assert getattr(excinfo.value, "code", None) is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_choices_must_be_list() -> None:
    recorder = HttpRecorder()
    client = httpx.AsyncClient(
        transport=recorder.transport(
            [ScriptedHttp(200, json_payload={"model": "m", "choices": {"0": {"message": {"content": "x"}}}})]
        ),
        follow_redirects=False,
    )
    adapter = GoChatAdapter(
        base_url=GO_BASE,
        model="deepseek-v4.1-flash",
        api_key=SensitiveValue("sk-synthetic"),
        session_id="conv-1",
        client=client,
        retry=RetryController(RetryPolicy(max_attempts=1)),
    )
    with pytest.raises(Exception) as excinfo:
        await adapter.generate(go_request())
    assert getattr(excinfo.value, "code", None) is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_fake_jev_records_partial_usage() -> None:
    ledger = CallLedger()
    fake = FakeJev(
        [ScriptedJevReply(usage=None, answers={})],
        ledger=ledger,
    )
    from agentqa.contracts.models import DecisionRequest

    result = await fake.decide(DecisionRequest(state="x", questions=[]))
    assert result.answers == {}
    totals = ledger.totals()
    assert totals.calls == 1
    assert totals.missing_usage_calls == 1
    assert totals.state == "unknown"


def test_error_taxonomy_matrix() -> None:
    assert classify_http_status(401).code is ErrorCode.PROVIDER_AUTH
    assert classify_http_status(403).code is ErrorCode.PROVIDER_AUTH
    assert classify_http_status(402).code is ErrorCode.PROVIDER_QUOTA
    rate = classify_http_status(429, headers={"retry-after": "3"})
    assert rate.code is ErrorCode.PROVIDER_RATE_LIMIT
    assert rate.retryable is True
    assert rate.retry_after == 3.0
    server = classify_http_status(503)
    assert server.code is ErrorCode.PROVIDER_TIMEOUT
    assert server.retryable is True
    assert classify_http_status(400).code is ErrorCode.PROVIDER_SCHEMA
    assert classify_http_status(400).retryable is False
    assert classify_http_status(301).code is ErrorCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_fake_go_keeps_usage_missing_distinct_from_zero() -> None:
    from agentqa.models.fakes import FakeGo, ScriptedGoReply

    ledger = CallLedger()
    fake = FakeGo([ScriptedGoReply(text="x", usage=None)], ledger=ledger)
    reply = await fake.generate(go_request())
    assert reply.usage is None
    totals = ledger.totals()
    assert totals.input_tokens is None
    assert totals.missing_usage_calls == 1


def test_usage_zero_is_reported_not_missing() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from agentqa.contracts.models import ModelCallOutcome, ModelCallRecord, ProviderRoute

    ledger = CallLedger()
    ledger.record(
        ModelCallRecord(
            call_id=uuid4(),
            attempt=1,
            purpose=MessagePurpose.DECIDE,
            requested_model="deepseek-v4.1-flash",
            route=ProviderRoute.OPENCODE_GO,
            usage=Usage(input_tokens=0, output_tokens=0, cached_tokens=0),
            outcome=ModelCallOutcome.SUCCEEDED,
            started_at=datetime(2026, 10, 9, tzinfo=UTC),
            ended_at=datetime(2026, 10, 9, tzinfo=UTC),
        )
    )
    totals = ledger.totals()
    assert totals.missing_usage_calls == 0
    assert totals.state == "complete"
