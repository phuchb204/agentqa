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
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    OutputFormat,
    ProviderRoute,
)
from agentqa.contracts.values import SensitiveValue
from agentqa.models.commandcode import CommandCodeChatAdapter, CommandCodeSystemOneAdapter
from agentqa.models.fakes import HttpRecorder, ScriptedHttp
from agentqa.models.opencode_go import GoChatAdapter
from agentqa.models.opencode_zen import ZenSystemOneAdapter
from agentqa.models.retry import RetryController, RetryPolicy
from agentqa.models.routes import MODEL_PAIRS, ROUTE_CATALOG
from agentqa.models.usage import CallLedger
from agentqa.models.wire import MODEL_ROUTE_ORIGINS, ModelTransportError, ensured_url

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "models"
GO_BASE = "https://opencode.ai/zen/go/v1"
ZEN_BASE = "https://opencode.ai/zen/v1"
CC_BASE = "https://api.commandcode.ai/provider/v1"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeBudget:
    def __init__(self) -> None:
        self.reservations: list[tuple[str, int]] = []
        self.settlements: list[tuple[str, int]] = []
        self._counter = 0

    def reserve(self, resource: str, amount: int) -> str:
        self._counter += 1
        reservation = f"res-{self._counter}"
        self.reservations.append((resource, amount))
        return reservation

    def settle(self, reservation_id: str, actual: int) -> None:
        self.settlements.append((reservation_id, actual))

    def remaining(self, resource: str) -> int:
        return 10


def go_request() -> GenerationRequest:
    return GenerationRequest(
        purpose=MessagePurpose.DECIDE,
        schema_name="policy",
        schema_version="1",
        prompt_ref="prompt://1",
        output_format=OutputFormat.TEXT,
        messages=[
            GenerationMessage(
                role=GenerationMessageRole.USER,
                parts=[GenerationTextPart(text="bước kế tiếp")],
            )
        ],
    )


def make_go(recorder: HttpRecorder, script: list[ScriptedHttp], **kwargs) -> GoChatAdapter:
    client = httpx.AsyncClient(transport=recorder.transport(script), follow_redirects=False)
    return GoChatAdapter(
        base_url=GO_BASE,
        model="deepseek-v4.1-flash",
        api_key=SensitiveValue("sk-synthetic"),
        session_id="conv-1",
        client=client,
        retry=kwargs.pop("retry", RetryController(RetryPolicy(max_attempts=1))),
        **kwargs,
    )


def test_route_allowlist_contains_exactly_four_pinned_routes() -> None:
    assert set(MODEL_ROUTE_ORIGINS) == {
        ProviderRoute.OPENCODE_GO,
        ProviderRoute.OPENCODE_ZEN,
        ProviderRoute.COMMANDCODE_CHAT,
        ProviderRoute.COMMANDCODE_SYSTEMONE,
    }
    assert MODEL_ROUTE_ORIGINS[ProviderRoute.OPENCODE_GO] == GO_BASE
    assert MODEL_ROUTE_ORIGINS[ProviderRoute.OPENCODE_ZEN] == ZEN_BASE
    assert MODEL_ROUTE_ORIGINS[ProviderRoute.COMMANDCODE_CHAT] == CC_BASE
    assert MODEL_ROUTE_ORIGINS[ProviderRoute.COMMANDCODE_SYSTEMONE] == CC_BASE
    assert ensured_url(ProviderRoute.OPENCODE_GO, GO_BASE).endswith("/chat/completions")
    assert ensured_url(ProviderRoute.OPENCODE_ZEN, ZEN_BASE).endswith("/systemone")
    assert ensured_url(ProviderRoute.COMMANDCODE_CHAT, CC_BASE).endswith("/chat/completions")
    assert ensured_url(ProviderRoute.COMMANDCODE_SYSTEMONE, CC_BASE).endswith("/systemone")


def test_route_catalog_covers_every_allowlisted_route_with_pair() -> None:
    assert set(ROUTE_CATALOG) == set(MODEL_ROUTE_ORIGINS)
    for pair_routes in MODEL_PAIRS.values():
        assert len(pair_routes) == 2
        families = {ROUTE_CATALOG[route].family for route in pair_routes}
        assert families == {"chat", "systemone"}
    assert {spec.key_env for spec in ROUTE_CATALOG.values()} == {
        "AGENTQA_LLM_API_KEY",
        "AGENTQA_JEV_API_KEY",
        "AGENTQA_CMD_API_KEY",
    }


def test_commandcode_adapters_use_own_routes_and_no_session_header() -> None:
    chat = CommandCodeChatAdapter(
        base_url=CC_BASE,
        model="deepseek/deepseek-v4.1-flash",
        api_key=SensitiveValue("sk-synthetic"),
    )
    assert chat.route is ProviderRoute.COMMANDCODE_CHAT
    assert "x-opencode-session" not in chat._headers()
    assert chat._headers()["user-agent"].startswith("AgentQA/")
    decision = CommandCodeSystemOneAdapter(
        base_url=CC_BASE,
        model="typesafe/jev",
        api_key=SensitiveValue("sk-synthetic"),
    )
    assert decision.route is ProviderRoute.COMMANDCODE_SYSTEMONE


def test_adapter_rejects_unlisted_destination() -> None:
    with pytest.raises(ModelTransportError) as go_error:
        GoChatAdapter(
            base_url="https://evil.example/zen/go/v1",
            model="deepseek-v4.1-flash",
            api_key=SensitiveValue("sk-x"),
            session_id="conv-1",
        )
    assert go_error.value.code is ErrorCode.PERMISSION_DENIED
    with pytest.raises(ModelTransportError) as zen_error:
        ZenSystemOneAdapter(
            base_url="https://opencode.ai.evil.example/zen/v1",
            model="jev-1.13-free",
            api_key=SensitiveValue("sk-x"),
        )
    assert zen_error.value.code is ErrorCode.PERMISSION_DENIED
    with pytest.raises(ModelTransportError):
        ensured_url(ProviderRoute.OPENCODE_GO, "http://opencode.ai/zen/go/v1")


@pytest.mark.asyncio
async def test_budget_reservation_wraps_each_dispatch() -> None:
    recorder = HttpRecorder()
    budget = FakeBudget()
    adapter = make_go(
        recorder,
        [ScriptedHttp(200, json_payload=load_fixture("go_chat_text.json"))],
        retry=RetryController(RetryPolicy(max_attempts=1), budget=budget),
    )
    await adapter.generate(go_request())
    assert recorder.count == 1
    assert budget.reservations == [("model_call", 1)]
    assert budget.settlements == [("res-1", 1)]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_no_hidden_retries_lose_calls() -> None:
    recorder = HttpRecorder()
    ledger = CallLedger()
    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    adapter = make_go(
        recorder,
        [ScriptedHttp(500), ScriptedHttp(500), ScriptedHttp(500)],
        ledger=ledger,
        retry=RetryController(RetryPolicy(max_attempts=3, base_delay=0.1), sleeper=sleeper),
    )
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(go_request())
    assert excinfo.value.code is ErrorCode.PROVIDER_TIMEOUT
    assert recorder.count == 3
    assert len(ledger.records) == 3
    assert [record.attempt for record in ledger.records] == [1, 2, 3]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_redirect_response_not_followed_even_for_json_looking_body() -> None:
    recorder = HttpRecorder()
    adapter = make_go(
        recorder,
        [ScriptedHttp(307, headers={"location": "https://mirror.example/v1/chat/completions"})],
    )
    with pytest.raises(ModelTransportError) as excinfo:
        await adapter.generate(go_request())
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert recorder.count == 1
    await adapter.aclose()


@pytest.mark.asyncio
async def test_zen_choice_answer_still_validated_against_criteria() -> None:
    recorder = HttpRecorder()
    client = httpx.AsyncClient(
        transport=recorder.transport([ScriptedHttp(200, json_payload=load_fixture("zen_choice.json"))]),
        follow_redirects=False,
    )
    adapter = ZenSystemOneAdapter(
        base_url=ZEN_BASE,
        model="jev-1.13-free",
        api_key=SensitiveValue("sk-synthetic"),
        client=client,
        ledger=CallLedger(),
    )
    result = await adapter.decide(
        DecisionRequest(
            state="x",
            questions=[
                ChoiceQuestion(
                    question_id="next_action",
                    instructions="Chọn",
                    criteria={"click_login": "Đăng nhập", "click_cancel": "Huỷ"},
                )
            ],
        )
    )
    assert isinstance(result.answers["next_action"], ChoiceAnswer)
    await adapter.aclose()
