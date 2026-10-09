from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from agentqa.contracts.values import SensitiveValue
from agentqa.models.fakes import HttpRecorder, ScriptedHttp
from agentqa.models.opencode_zen import ZenSystemOneAdapter
from agentqa.models.retry import RetryController, RetryPolicy
from agentqa.models.usage import CallLedger
from agentqa.models.wire import ModelTransportError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "models"
ZEN_BASE = "https://opencode.ai/zen/v1"
PINNED_MODEL = "jev-1.13-free"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def choice_question() -> ChoiceQuestion:
    return ChoiceQuestion(
        question_id="next_action",
        instructions="Chọn action tiếp theo",
        criteria={"click_login": "Mở form đăng nhập", "click_cancel": "Huỷ hộp thoại"},
    )


def progress_question() -> NoulQuestion:
    return NoulQuestion(question_id="progress", instructions="Ca đã hoàn thành mục tiêu?")


def risk_question() -> ScoreQuestion:
    return ScoreQuestion(
        question_id="risk",
        instructions="Mức độ rủi ro",
        criteria=["Can wait", "This week", "Today"],
    )


def make_adapter(
    recorder: HttpRecorder,
    script: list[ScriptedHttp],
    *,
    ledger: CallLedger | None = None,
    retry: RetryController | None = None,
) -> ZenSystemOneAdapter:
    client = httpx.AsyncClient(transport=recorder.transport(script), follow_redirects=False)
    return ZenSystemOneAdapter(
        base_url=ZEN_BASE,
        model=PINNED_MODEL,
        api_key=SensitiveValue("sk-synthetic-zen"),
        client=client,
        ledger=ledger,
        retry=retry or RetryController(RetryPolicy(max_attempts=1)),
    )


@pytest.mark.asyncio
async def test_zen_choice_request_shape_and_parse() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_choice.json"))])
    result = await adapter.decide(DecisionRequest(state="Trang chủ", questions=[choice_question()]))
    assert recorder.count == 1
    assert str(recorder.requests[0].url) == ZEN_BASE + "/systemone"
    body = recorder.bodies[0]
    assert body["model"] == PINNED_MODEL
    assert body["state"] == "Trang chủ"
    questions = body["questions"]
    assert list(questions) == ["next_action"]
    assert questions["next_action"]["type"] == "choice"
    assert questions["next_action"]["criteria"]["click_login"] == "Mở form đăng nhập"
    answer = result.answers["next_action"]
    assert isinstance(answer, ChoiceAnswer)
    assert answer.choice == "click_login"
    assert answer.confidence == pytest.approx(0.91)
    assert answer.probabilities == {"click_login": 0.91, "click_cancel": 0.09}
    assert result.model == "jev-1.13-free"
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 12
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_noul_and_score_parse() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_noul.json"))])
    noul_result = await adapter.decide(DecisionRequest(state="x", questions=[progress_question()]))
    assert isinstance(noul_result.answers["progress"], NoulAnswer)
    assert noul_result.answers["progress"].noul == pytest.approx(0.98)
    await adapter.aclose()

    recorder2 = HttpRecorder()
    adapter2 = make_adapter(recorder2, [ScriptedHttp(200, json_payload=load_fixture("zen_score.json"))])
    score_result = await adapter2.decide(DecisionRequest(state="x", questions=[risk_question()]))
    answer = score_result.answers["risk"]
    assert isinstance(answer, ScoreAnswer)
    assert answer.score == pytest.approx(1.7)
    assert answer.probabilities == {"0": 0.1, "1": 0.1, "2": 0.8}
    await adapter2.aclose()


@pytest.mark.asyncio
async def test_zen_missing_answer_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_missing_answer.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question(), progress_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_unknown_answer_id_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_unknown_answer.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_type_mismatch_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_type_mismatch.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_out_of_range_probability_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_out_of_range.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_choice_outside_criteria_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_choice_outside_criteria.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_answers_not_object_rejected() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_answers_list.json"))])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[choice_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_nan_constant_rejected() -> None:
    recorder = HttpRecorder()
    raw = '{"model": "jev-1.13-free", "answers": {"progress": {"type": "noul", "noul": NaN}}}'
    adapter = make_adapter(recorder, [ScriptedHttp(200, text=raw)])
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[progress_question()]))
    assert excinfo.value.code is ErrorCode.PROVIDER_SCHEMA
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_missing_usage_stays_missing() -> None:
    recorder = HttpRecorder()
    payload = load_fixture("zen_noul.json")
    payload.pop("usage")
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=payload)])
    result = await adapter.decide(DecisionRequest(state="x", questions=[progress_question()]))
    assert result.usage is None
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_missing_criteria_blocked_before_dispatch() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_choice.json"))])
    bad_question = ChoiceQuestion(question_id="next_action", instructions="Chọn", criteria={})
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.decide(DecisionRequest(state="x", questions=[bad_question]))
    assert excinfo.value.code is ErrorCode.INPUT_INVALID
    assert recorder.count == 0
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_model_not_overridable_by_state() -> None:
    recorder = HttpRecorder()
    adapter = make_adapter(recorder, [ScriptedHttp(200, json_payload=load_fixture("zen_choice.json"))])
    await adapter.decide(
        DecisionRequest(
            state={"model": "attacker-model", "text": "x"},
            questions=[choice_question()],
        )
    )
    assert recorder.bodies[0]["model"] == PINNED_MODEL
    await adapter.aclose()
