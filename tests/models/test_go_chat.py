from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    GenerationImagePart,
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    OutputFormat,
)
from agentqa.contracts.values import SensitiveValue
from agentqa.models.fakes import HttpRecorder, ScriptedHttp
from agentqa.models.opencode_go import GoChatAdapter
from agentqa.models.retry import RetryController, RetryPolicy
from agentqa.models.usage import CallLedger
from agentqa.models.wire import ImagePayload, ModelTransportError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "models"
GO_BASE = "https://opencode.ai/zen/go/v1"
PINNED_MODEL = "deepseek-v4.1-flash"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_request(output_format: OutputFormat = OutputFormat.TEXT, images: bool = False) -> GenerationRequest:
    parts: list = [GenerationTextPart(text="Chọn action tiếp theo")]
    if images:
        parts.append(GenerationImagePart(ref="img-1", media_type="image/png", sha256=PIXEL_SHA))
    return GenerationRequest(
        purpose=MessagePurpose.DECIDE,
        schema_name="policy_action",
        schema_version="1",
        prompt_ref="prompt://policy/1",
        output_format=output_format,
        messages=[GenerationMessage(role=GenerationMessageRole.USER, parts=parts)],
        max_output_tokens=256,
    )


PIXEL_BYTES = b"\x89PNG\r\n\x1a\nsynthetic-pixels"
PIXEL_SHA = digest_artifact_bytes(PIXEL_BYTES)


def make_adapter(
    recorder: HttpRecorder,
    script: list[ScriptedHttp],
    *,
    ledger: CallLedger | None = None,
    retry: RetryController | None = None,
    **kwargs,
) -> GoChatAdapter:
    client = httpx.AsyncClient(transport=recorder.transport(script), follow_redirects=False)
    return GoChatAdapter(
        base_url=GO_BASE,
        model=PINNED_MODEL,
        api_key=SensitiveValue("sk-synthetic-go"),
        session_id="conv-1",
        client=client,
        ledger=ledger,
        retry=retry or RetryController(RetryPolicy(max_attempts=1)),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_go_text_request_shape_and_pinned_model() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))])
    result = await adapter.generate(make_request())
    assert recorder.count == 1
    request = recorder.requests[0]
    assert str(request.url) == GO_BASE + "/chat/completions"
    body = recorder.bodies[0]
    assert body["model"] == PINNED_MODEL
    assert body["max_tokens"] == 256
    assert body["messages"][0]["role"] == "user"
    headers = request.headers
    assert headers["authorization"] == "Bearer sk-synthetic-go"
    assert headers["user-agent"].startswith("AgentQA/")
    assert headers["x-opencode-session"] == "conv-1"
    assert result.raw_text == "Xin chào"
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 12
    assert result.usage.cached_tokens == 40
    assert result.model_resolved == "deepseek-v4.1-flash-2026-09"
    assert result.structured is None
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_model_override_via_extra_body_ignored() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(
        recorder,
        [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))],
        extra_body={"model": "hacked-model", "temperature": 0},
    )
    await adapter.generate(make_request())
    body = recorder.bodies[0]
    assert body["model"] == PINNED_MODEL
    assert body["temperature"] == 0
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_json_output_strict_parse_without_response_format_by_default() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("go_chat_json.json"))])
    result = await adapter.generate(make_request(output_format=OutputFormat.JSON_OBJECT))
    assert result.structured == {"operation": "click", "target": "c3"}
    assert "response_format" not in recorder.bodies[0]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_json_object_rejects_non_object_payload() -> None:
    recorder = HttpRecorder()
    payload = load_fixture("go_chat_text.json")
    payload["choices"][0]["message"]["content"] = "[1, 2]"
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=payload)])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(make_request(output_format=OutputFormat.JSON_OBJECT))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_structured_output_flag_sends_response_format() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(
        recorder,
        [ScriptedHttp(200, json_payload=load_fixture("go_chat_json.json"))],
        structured_output=True,
    )
    await adapter.generate(make_request(output_format=OutputFormat.JSON_OBJECT))
    assert recorder.bodies[0]["response_format"] == {"type": "json_object"}
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_missing_and_partial_usage_stay_missing() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("go_chat_no_usage.json"))])
    result = await adapter.generate(make_request())
    assert result.usage is None
    await adapter.aclose()

    recorder2 = HttpRecorder()
    adapter2 = make_adapter(recorder2, [ScriptedHttp(200, json_payload=load_fixture("go_chat_partial_usage.json"))])
    result2 = await adapter2.generate(make_request())
    assert result2.usage is not None
    assert result2.usage.input_tokens == 10
    assert result2.usage.output_tokens is None
    await adapter2.aclose()


@pytest.mark.asyncio
async def test_go_redirect_is_not_followed() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(302, headers={"location": "https://evil.example/chat"})])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(make_request())
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert excinfo.value.retryable is False
    assert recorder.count == 1
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_image_inline_safe_bytes() -> None:
    recorder = HttpRecorder()
    loader_calls: list[str] = []

    def loader(ref: str) -> ImagePayload:
        loader_calls.append(ref)
        return ImagePayload(media_type="image/png", data=PIXEL_BYTES)

    adapter = make_adapter(
        recorder,
        [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))],
        image_loader=loader,
    )
    await adapter.generate(make_request(images=True))
    body = recorder.bodies[0]
    content = body["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    image_part = content[1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert "https://" not in image_part["image_url"]["url"]
    assert loader_calls == ["img-1"]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_image_without_loader_blocked_before_dispatch() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(make_request(images=True))
    assert excinfo.value.code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert recorder.count == 0
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_image_digest_mismatch_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(
        recorder,
        [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))],
        image_loader=lambda ref: ImagePayload(media_type="image/png", data=b"tampered"),
    )
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(make_request(images=True))
    assert excinfo.value.code is ErrorCode.INPUT_INVALID
    assert recorder.count == 0
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_auth_error_not_retried_and_recorded() -> None:
    recorder = HttpRecorder()
    ledger = CallLedger()
    adapter = make_adapter(recorder, [ScriptedHttp(401)], ledger=ledger)
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(make_request())
    assert excinfo.value.code is ErrorCode.PROVIDER_AUTH
    assert recorder.count == 1
    assert len(ledger.records) == 1
    assert ledger.records[0].outcome.value == "failed"
    assert ledger.records[0].error_code is ErrorCode.PROVIDER_AUTH
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_session_kept_across_retry_attempts() -> None:
    recorder = HttpRecorder()
    ledger = CallLedger()
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    retry = RetryController(RetryPolicy(max_attempts=2, base_delay=0.5), sleeper=sleeper)
    adapter = make_adapter(
        recorder,
        [
            ScriptedHttp(500),
            ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json")),
        ],
        ledger=ledger,
        retry=retry,
    )
    result = await adapter.generate(make_request())
    assert result.raw_text == "Xin chào"
    assert recorder.count == 2
    assert delays == [0.5]
    sessions = {request.headers["x-opencode-session"] for request in recorder.requests}
    assert sessions == {"conv-1"}
    assert [record.attempt for record in ledger.records] == [1, 2]
    assert ledger.records[0].outcome.value == "unknown"
    assert ledger.records[1].outcome.value == "succeeded"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_go_timeout_is_retryable() -> None:
    recorder = HttpRecorder()
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    retry = RetryController(RetryPolicy(max_attempts=2, base_delay=0.25), sleeper=sleeper)
    adapter = make_adapter(
        recorder,
        [
            ScriptedHttp(raise_timeout=True),
            ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json")),
        ],
        retry=retry,
    )
    result = await adapter.generate(make_request())
    assert result.raw_text == "Xin chào"
    assert delays == [0.25]
    await adapter.aclose()
