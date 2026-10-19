from __future__ import annotations

from pathlib import Path

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


def test_manifest_budgets_default_to_opencode_pair() -> None:
    from agentqa.platform.calibration.models import Budgets as CalibrationBudgets
    from agentqa.platform.experiments.manifests import Budgets as ExperimentBudgets

    calibration = CalibrationBudgets(max_calls=10, max_cost_usd=1.0, routes={"opencode_go": "m"})
    assert calibration.model_pair == "opencode"
    experiment = ExperimentBudgets(max_calls=10, max_cost_usd=1.0)
    assert experiment.model_pair == "opencode"


def test_manifest_budgets_reject_unknown_pair() -> None:
    from agentqa.contracts.errors import AgentQAValidationError
    from agentqa.platform.calibration.models import Budgets as CalibrationBudgets
    from agentqa.platform.experiments.manifests import Budgets as ExperimentBudgets

    with pytest.raises(AgentQAValidationError):
        CalibrationBudgets(max_calls=10, max_cost_usd=1.0, routes={"x": "y"}, model_pair="acme")
    with pytest.raises(AgentQAValidationError):
        ExperimentBudgets(max_calls=10, max_cost_usd=1.0, model_pair="acme")


def test_commandcode_yaml_manifests_pin_commandcode_pair() -> None:
    import yaml

    from agentqa.platform.calibration import load_manifest
    from agentqa.platform.experiments import ExperimentManifest

    repo = Path(__file__).resolve().parents[2]
    calibration = load_manifest(repo / "benchmarks" / "calibration" / "manifest-commandcode.yaml")
    assert calibration.budgets.model_pair == "commandcode"
    assert set(calibration.budgets.routes) == {"commandcode_chat", "commandcode_systemone"}
    for name in ("rq1-commandcode.yaml", "rq2-commandcode.yaml", "rq3-commandcode.yaml"):
        document = yaml.safe_load((repo / "benchmarks" / "experiments" / name).read_text(encoding="utf-8"))
        manifest = ExperimentManifest.model_validate(document)
        assert manifest.budgets.model_pair == "commandcode"
        assert set(manifest.budgets.routes) == {"commandcode_chat", "commandcode_systemone"}


def test_cli_guard_rejects_pair_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentqa.platform.cli import CliInputError, _require_model_pair

    monkeypatch.setenv("AGENTQA_MODEL_PAIR", "opencode")
    _require_model_pair("opencode")
    with pytest.raises(CliInputError):
        _require_model_pair("commandcode")


def test_chat_image_gate_reads_pair_receipt(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from agentqa.platform.experiments import live as experiment_live

    def write_receipt(name: str, image: str, expires: str) -> None:
        (tmp_path / name).write_text(
            json.dumps({"capabilities": {"image": image}, "expires_at": expires}), encoding="utf-8"
        )

    monkeypatch.setattr(experiment_live, "CAPABILITY_DIR", tmp_path)
    write_receipt("commandcode_chat-new.json", "verified", "2099-01-01T00:00:00Z")
    assert experiment_live.chat_image_verified("commandcode") is True
    assert experiment_live.chat_image_verified("opencode") is False
    assert experiment_live.chat_image_verified("acme") is False
    (tmp_path / "commandcode_chat-new.json").unlink()
    write_receipt("commandcode_chat-old.json", "verified", "2020-01-01T00:00:00Z")
    assert experiment_live.chat_image_verified("commandcode") is False
    (tmp_path / "commandcode_chat-old.json").unlink()
    write_receipt("commandcode_chat-blocked.json", "blocked", "2099-01-01T00:00:00Z")
    assert experiment_live.chat_image_verified("commandcode") is False


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
