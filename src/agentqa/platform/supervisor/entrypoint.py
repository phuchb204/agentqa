from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agentqa.agent.browser import BrowserSession, PlaywrightActionPort, PlaywrightReadPort, SafeEvidenceService
from agentqa.agent.browser.capture import MaskRegion
from agentqa.agent.browser.files import DirectoryFileResolver
from agentqa.agent.browser.journals import DownloadJournal, NetworkJournal
from agentqa.agent.replay import PlaywrightSceneProvider
from agentqa.contracts.actions import ActionCommand, ActionReceipt
from agentqa.contracts.values import SensitiveValue
from agentqa.platform.fixtures import (
    CanvasdeskFixture,
    FixtureRegistry,
    ShopflowFixture,
    TaskboardFixture,
    canvasdesk_password,
    shopflow_password,
    synthetic_password,
)
from agentqa.platform.runs.composition import AgentModels
from agentqa.platform.runs.coordinator import BridgedFixtureRuns, BridgedRunEventRecorder, RunCoordinator
from agentqa.platform.runs.facts import DirectoryBaselineResolver
from agentqa.platform.security.egress import AllowedEndpoint, EgressPolicy, system_resolver
from agentqa.platform.security.proxy import EgressProxy
from agentqa.platform.security.redaction import RedactionService
from agentqa.platform.security.sandbox import select_profile
from agentqa.platform.security.taint import TaintRegistry
from agentqa.platform.supervisor.db_bridge import SelectorJournalBridge
from agentqa.platform.supervisor.runtime import RuntimeConfig, SupervisorRuntime
from agentqa.platform.supervisor.server import SupervisorServer


class NullRedactor:
    def redact_text(self, text: str) -> str:
        return text

    def redact_structure(self, value: Any) -> Any:
        return value


@dataclass(frozen=True)
class MemoryArtifact:
    data: bytes
    media_type: str


class MemorySink:
    def __init__(self) -> None:
        self.count = 0
        self.records: dict[str, MemoryArtifact] = {}

    def put(self, label: str, payload: bytes, media_type: str) -> str:
        self.count += 1
        ref = f"mem://{label}/{self.count}"
        self.records[ref] = MemoryArtifact(data=payload, media_type=media_type)
        return ref

    def get(self, ref: str) -> MemoryArtifact:
        record = self.records.get(ref)
        if record is None:
            raise KeyError(ref)
        return record


class FaultSink(MemorySink):
    def put(self, label: str, payload: bytes, media_type: str) -> str:
        raise OSError("storage fault injected")


class FixtureSecretBroker:
    def __init__(self) -> None:
        self._namespace: str | None = None

    def set_namespace(self, namespace: str) -> None:
        self._namespace = namespace

    def resolve(self, grant_ref: str) -> SensitiveValue:
        parts = grant_ref.split(".")
        if len(parts) == 3 and self._namespace:
            app, user, field = parts
            password_factory = {
                "taskboard": synthetic_password,
                "shopflow": shopflow_password,
                "canvasdesk": canvasdesk_password,
            }.get(app)
            if password_factory is not None:
                if field == "password":
                    return SensitiveValue(password_factory(self._namespace, user))
                return SensitiveValue(user)
        raise KeyError(f"grant '{grant_ref}' không resolve được")


def register_fixture_endpoint(registry: FixtureRegistry, value: str) -> None:
    parts = value.split("|")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"fixture endpoint phải là 'fixture_id@version|base_url|control_token': {value!r}")
    ref, base_url, control_token = parts
    fixture_id = ref.partition("@")[0]
    handlers = {
        "taskboard": TaskboardFixture,
        "shopflow": ShopflowFixture,
        "canvasdesk": CanvasdeskFixture,
    }
    handler = handlers.get(fixture_id)
    if handler is None:
        raise ValueError(f"fixture '{fixture_id}' không được hỗ trợ")
    registry.register(handler(base_url, control_token))


class LossExecutor:
    def __init__(self, inner: PlaywrightActionPort, trigger_intent: str) -> None:
        self._inner = inner
        self._trigger = trigger_intent

    async def dispatch(self, command: ActionCommand) -> ActionReceipt:
        receipt = await self._inner.dispatch(command)
        if (
            command.target is not None
            and command.target.intent == self._trigger
            and receipt.outcome.value == "succeeded"
        ):
            raise TimeoutError("response lost sau side effect")
        return receipt


class LazyContextExecutor:
    def __init__(self, port: PlaywrightActionPort, contexts: Any) -> None:
        self._port = port
        self._contexts = contexts

    async def dispatch(self, command: ActionCommand) -> ActionReceipt:
        key = str(command.run_id)
        if key not in self._contexts.context_keys():
            await self._contexts.open(key)
        return await self._port.dispatch(command)


def parse_endpoint(value: str) -> AllowedEndpoint:
    parts = value.split(":")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(f"endpoint phải là host:port: {value!r}")
    host = parts[0]
    port = int(parts[1])
    addresses = (parts[2],) if len(parts) > 2 else ((host,) if _is_literal(host) else ("127.0.0.1",))
    return AllowedEndpoint(host=host, port=port, addresses=addresses)


def _is_literal(host: str) -> bool:
    return all(part.isdigit() for part in host.split(".") if part != "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--supervisor-id", required=True)
    parser.add_argument("--fence-epoch", type=int, default=1)
    parser.add_argument("--lease-seconds", type=float, default=30.0)
    parser.add_argument("--control-token", required=True)
    parser.add_argument("--allow-origin", action="append", type=parse_endpoint, default=[])
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--fixture-base-url", default="")
    parser.add_argument("--fixture-control-token", default="")
    parser.add_argument("--fixture-endpoint", action="append", default=[])
    parser.add_argument("--baseline-dir", default="")
    parser.add_argument("--fault-loss-intent", default="")
    parser.add_argument("--fault-storage", action="store_true")
    parser.add_argument("--agent-models", choices=["none", "fake", "live"], default="none")
    parser.add_argument("--agent-script", default="")
    parser.add_argument("--upload-dir", default="")
    return parser


async def run(args: argparse.Namespace) -> None:
    policy = EgressPolicy(args.allow_origin, resolver=system_resolver)
    proxy = EgressProxy(policy)
    await proxy.start()
    temp_root = tempfile.mkdtemp(prefix="agentqa-supervisor-")
    profile = select_profile(
        workspace_root=_workspace_root(),
        temp_root=temp_root,
        proxy_url=proxy.url,
    )
    session = BrowserSession(profile.launch)
    await session.start()
    sink = FaultSink() if args.fault_storage else MemorySink()
    taint = TaintRegistry()
    evidence = SafeEvidenceService(redactor=RedactionService(taint), sink=sink, taint=taint)
    broker = FixtureSecretBroker()
    file_resolver = DirectoryFileResolver(args.upload_dir) if args.upload_dir else None
    downloads = DownloadJournal()
    network = NetworkJournal()
    action_port = PlaywrightActionPort(
        session.contexts,
        evidence,
        secret_resolver=broker,
        navigation_guard=policy,
        file_resolver=file_resolver,
        downloads=downloads,
    )
    executor: Any = LazyContextExecutor(action_port, session.contexts)
    if args.fault_loss_intent:
        executor = LossExecutor(action_port, args.fault_loss_intent)
    read_port = PlaywrightReadPort(session.contexts, evidence, network=network, downloads=downloads)
    bridge = SelectorJournalBridge(
        dsn=args.dsn,
        workspace_id=UUID(args.workspace_id),
        principal_id=UUID(args.principal_id),
        supervisor_id=args.supervisor_id,
    )
    bridge.start()
    runtime = SupervisorRuntime(
        bridge,
        executor,
        RuntimeConfig(
            supervisor_id=args.supervisor_id,
            fence_epoch=args.fence_epoch,
            lease_seconds=args.lease_seconds,
        ),
    )
    fixture_registry = FixtureRegistry()
    if args.fixture_base_url:
        fixture_registry.register(TaskboardFixture(args.fixture_base_url, args.fixture_control_token))
    for endpoint in args.fixture_endpoint:
        register_fixture_endpoint(fixture_registry, endpoint)
    baseline_resolver = DirectoryBaselineResolver(Path(args.baseline_dir)) if args.baseline_dir else None
    agent_models = AgentModels()
    if args.agent_models == "fake":
        if args.agent_script:
            from importlib import import_module
            from pathlib import Path as _Path

            module = import_module("tests.support.agent_models")
            agent_models = module.load_agent_models(_Path(args.agent_script))
        else:
            from agentqa.models.fakes import FakeGo, FakeJev

            agent_models = AgentModels(generative=FakeGo(), decision=FakeJev())
    if args.agent_models == "live":
        agent_models = _build_live_models(sink)
    fixture_runs = BridgedFixtureRuns(bridge, args.dsn, fixture_registry)
    coordinator = RunCoordinator(
        runtime=runtime,
        contexts=session.contexts,
        read_port=read_port,
        scene_provider=PlaywrightSceneProvider(session.contexts),
        fixtures=fixture_registry,
        recorder=BridgedRunEventRecorder(bridge, args.dsn),
        secret_namespace_hook=broker.set_namespace,
        agent_models=agent_models,
        taint=taint,
        fixture_runs=fixture_runs,
        baseline_resolver=baseline_resolver,
    )
    frame_state = {"seq": 0}

    async def latest_frame(context_key: str) -> dict[str, Any] | None:
        try:
            page = await session.contexts.page(context_key)
            png = await page.screenshot(type="png")
            boxes = await page.evaluate(
                "() => Array.from(document.querySelectorAll('input[type=password]')).map((el) => {"
                " const r = el.getBoundingClientRect();"
                " return {x: r.x, y: r.y, width: r.width, height: r.height}; })"
            )
            regions = [
                MaskRegion(x=int(box["x"]), y=int(box["y"]), width=int(box["width"]), height=int(box["height"]))
                for box in boxes
            ]
            masked = evidence.mask_image(png, regions)
        except Exception:
            return None
        frame_state["seq"] += 1
        viewport = page.viewport_size or {}
        return {
            "seq": frame_state["seq"],
            "viewport": {"width": int(viewport.get("width", 0)), "height": int(viewport.get("height", 0))},
            "dpr": 1.0,
            "png_b64": base64.b64encode(masked).decode("ascii"),
        }

    server = SupervisorServer(
        runtime,
        token=args.control_token,
        port=args.port,
        coordinator=coordinator,
        frame_provider=latest_frame,
    )
    port = await server.start()
    print(json.dumps({"port": port, "proxy": proxy.url}), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()
        await session.close()
        await proxy.stop()
        bridge.stop()


LIVE_ROUTE_DEFAULTS = {
    "opencode_go": ("AGENTQA_LLM_API_KEY", "AGENTQA_LLM_BASE_URL", "AGENTQA_LLM_MODEL"),
    "opencode_zen": ("AGENTQA_JEV_API_KEY", "AGENTQA_JEV_BASE_URL", "AGENTQA_JEV_MODEL"),
    "commandcode_chat": ("AGENTQA_CMD_API_KEY", "AGENTQA_CMD_BASE_URL", "AGENTQA_CMD_CHAT_MODEL"),
    "commandcode_systemone": ("AGENTQA_CMD_API_KEY", "AGENTQA_CMD_BASE_URL", "AGENTQA_CMD_DECISION_MODEL"),
}
LIVE_BASE_DEFAULTS = {
    "opencode_go": "https://opencode.ai/zen/go/v1",
    "opencode_zen": "https://opencode.ai/zen/v1",
    "commandcode_chat": "https://api.commandcode.ai/provider/v1",
    "commandcode_systemone": "https://api.commandcode.ai/provider/v1",
}
LIVE_MODEL_DEFAULTS = {
    "opencode_go": "deepseek-v4.1-flash",
    "opencode_zen": "jev-1.13-free",
    "commandcode_chat": "deepseek/deepseek-v4.1-flash",
    "commandcode_systemone": "typesafe/jev",
}
MODEL_PAIR_ROUTES = {
    "opencode": ("opencode_go", "opencode_zen"),
    "commandcode": ("commandcode_chat", "commandcode_systemone"),
}


def _build_live_models(sink: MemorySink) -> AgentModels:
    from agentqa.contracts.values import SensitiveValue
    from agentqa.models.commandcode import CommandCodeChatAdapter, CommandCodeSystemOneAdapter
    from agentqa.models.opencode_go import GoChatAdapter
    from agentqa.models.opencode_zen import ZenSystemOneAdapter
    from agentqa.models.wire import ImagePayload

    def load_image(ref: str) -> ImagePayload:
        artifact = sink.get(ref)
        return ImagePayload(media_type=artifact.media_type, data=artifact.data)

    def route_config(route: str) -> tuple[str, str, str]:
        key_env, base_env, model_env = LIVE_ROUTE_DEFAULTS[route]
        key = os.environ.get(key_env, "")
        if not key:
            raise SystemExit(f"live models cần biến môi trường {key_env}")
        base = os.environ.get(base_env) or LIVE_BASE_DEFAULTS[route]
        model = os.environ.get(model_env) or LIVE_MODEL_DEFAULTS[route]
        return key, base, model

    pair = os.environ.get("AGENTQA_MODEL_PAIR", "opencode")
    if pair not in MODEL_PAIR_ROUTES:
        raise SystemExit(f"AGENTQA_MODEL_PAIR không hỗ trợ: {pair} (chọn {sorted(MODEL_PAIR_ROUTES)})")
    chat_route, decision_route = MODEL_PAIR_ROUTES[pair]
    chat_key, chat_base, chat_model = route_config(chat_route)
    jev_key, jev_base, jev_model = route_config(decision_route)
    if chat_route == "commandcode_chat":
        generative = CommandCodeChatAdapter(
            base_url=chat_base,
            model=chat_model,
            api_key=SensitiveValue(chat_key),
            image_loader=load_image,
            structured_output=True,
        )
    else:
        generative = GoChatAdapter(
            base_url=chat_base,
            model=chat_model,
            api_key=SensitiveValue(chat_key),
            session_id=f"live-{uuid4().hex[:12]}",
            image_loader=load_image,
            structured_output=True,
        )
    if decision_route == "commandcode_systemone":
        decision = CommandCodeSystemOneAdapter(
            base_url=jev_base,
            model=jev_model,
            api_key=SensitiveValue(jev_key),
        )
    else:
        decision = ZenSystemOneAdapter(
            base_url=jev_base,
            model=jev_model,
            api_key=SensitiveValue(jev_key),
        )
    return AgentModels(generative=generative, decision=decision)


def _workspace_root() -> str:
    return os.environ.get("AGENTQA_WORKSPACE_ROOT", os.getcwd())


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
