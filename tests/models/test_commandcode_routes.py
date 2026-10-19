from __future__ import annotations

import pytest
from tools import model_conformance as mc

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import MessagePurpose, ProviderRoute
from agentqa.models.commandcode import CommandCodeChatAdapter, CommandCodeSystemOneAdapter
from agentqa.models.fakes import FakeGo, FakeJev, ScriptedGoReply, ScriptedJevReply
from agentqa.models.routes import (
    COMMANDCODE_PAIR,
    OPENCODE_PAIR,
    resolve_pair,
    route_spec,
)
from agentqa.models.usage import CallLedger
from agentqa.models.wire import ModelTransportError, ensured_url
from agentqa.platform.runs.composition import AgentModels, ledgered_composition


def test_resolve_pair_returns_chat_then_decision() -> None:
    chat, decision = resolve_pair(OPENCODE_PAIR)
    assert (chat, decision) == (ProviderRoute.OPENCODE_GO, ProviderRoute.OPENCODE_ZEN)
    chat, decision = resolve_pair(COMMANDCODE_PAIR)
    assert (chat, decision) == (ProviderRoute.COMMANDCODE_CHAT, ProviderRoute.COMMANDCODE_SYSTEMONE)


def test_resolve_pair_rejects_unknown_name() -> None:
    with pytest.raises(ModelTransportError) as excinfo:
        resolve_pair("acme")
    assert excinfo.value.code is ErrorCode.INPUT_INVALID


def test_route_spec_pins_commandcode_origins() -> None:
    chat = route_spec(ProviderRoute.COMMANDCODE_CHAT)
    assert chat.origin == "https://api.commandcode.ai/provider/v1"
    assert chat.default_model == "deepseek/deepseek-v4.1-flash"
    assert chat.key_env == "AGENTQA_CMD_API_KEY"
    assert ensured_url(chat.route, chat.origin) == chat.url
    decision = route_spec(ProviderRoute.COMMANDCODE_SYSTEMONE)
    assert decision.default_model == "typesafe/jev"
    assert decision.key_env == "AGENTQA_CMD_API_KEY"


def test_conformance_offline_accepts_commandcode_models() -> None:
    chat = mc.validate_offline(
        mc.build_parser().parse_args(
            [
                "--provider",
                "commandcode_chat",
                "--model",
                "deepseek/deepseek-v4.1-flash",
                "--max-calls",
                "4",
                "--max-output-tokens",
                "4096",
            ]
        )
    )
    assert chat["status"] == "validated_offline"
    decision = mc.validate_offline(
        mc.build_parser().parse_args(
            ["--provider", "commandcode_systemone", "--model", "typesafe/jev", "--max-calls", "4"]
        )
    )
    assert decision["status"] == "validated_offline"


def test_conformance_offline_rejects_wrong_commandcode_model() -> None:
    with pytest.raises(SystemExit) as excinfo:
        mc.validate_offline(
            mc.build_parser().parse_args(
                [
                    "--provider",
                    "commandcode_chat",
                    "--model",
                    "deepseek-v4.1-flash",
                    "--max-calls",
                    "4",
                    "--max-output-tokens",
                    "4096",
                ]
            )
        )
    assert excinfo.value.code == 64


def test_conformance_offline_requires_output_budget_for_commandcode_chat() -> None:
    with pytest.raises(SystemExit) as excinfo:
        mc.validate_offline(
            mc.build_parser().parse_args(
                [
                    "--provider",
                    "commandcode_chat",
                    "--model",
                    "deepseek/deepseek-v4.1-flash",
                    "--max-calls",
                    "4",
                ]
            )
        )
    assert excinfo.value.code == 64


@pytest.mark.asyncio
async def test_ledgered_composition_keeps_commandcode_routes() -> None:
    ledger = CallLedger()
    composition = AgentModels(
        generative=FakeGo(
            [ScriptedGoReply(text="ok")],
            model="deepseek/deepseek-v4.1-flash",
            route=ProviderRoute.COMMANDCODE_CHAT,
        ),
        decision=FakeJev(
            [ScriptedJevReply()],
            model="typesafe/jev",
            route=ProviderRoute.COMMANDCODE_SYSTEMONE,
        ),
    )
    ledgered = ledgered_composition(composition, ledger)
    assert ledgered.generative is not None
    assert ledgered.decision is not None
    assert ledgered.generative._route is ProviderRoute.COMMANDCODE_CHAT
    assert ledgered.decision._route is ProviderRoute.COMMANDCODE_SYSTEMONE


def test_commandcode_adapters_expose_own_wire_versions() -> None:
    assert CommandCodeChatAdapter.schema_version == "commandcode-chat/1"
    assert CommandCodeSystemOneAdapter.schema_version == "commandcode-systemone/1"
    assert MessagePurpose.DECIDE.value == "decide"
