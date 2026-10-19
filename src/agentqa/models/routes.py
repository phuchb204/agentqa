from __future__ import annotations

from dataclasses import dataclass

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ProviderRoute
from agentqa.models.wire import ModelTransportError

CHAT_FAMILY = "chat"
SYSTEMONE_FAMILY = "systemone"

OPENCODE_PAIR = "opencode"
COMMANDCODE_PAIR = "commandcode"


@dataclass(frozen=True)
class RouteSpec:
    route: ProviderRoute
    family: str
    origin: str
    path: str
    default_model: str
    key_env: str
    base_env: str
    model_env: str
    needs_session_header: bool
    label: str

    @property
    def url(self) -> str:
        return self.origin.rstrip("/") + self.path


ROUTE_CATALOG: dict[ProviderRoute, RouteSpec] = {
    ProviderRoute.OPENCODE_GO: RouteSpec(
        route=ProviderRoute.OPENCODE_GO,
        family=CHAT_FAMILY,
        origin="https://opencode.ai/zen/go/v1",
        path="/chat/completions",
        default_model="deepseek-v4.1-flash",
        key_env="AGENTQA_LLM_API_KEY",
        base_env="AGENTQA_LLM_BASE_URL",
        model_env="AGENTQA_LLM_MODEL",
        needs_session_header=True,
        label="OpenCode Go chat",
    ),
    ProviderRoute.OPENCODE_ZEN: RouteSpec(
        route=ProviderRoute.OPENCODE_ZEN,
        family=SYSTEMONE_FAMILY,
        origin="https://opencode.ai/zen/v1",
        path="/systemone",
        default_model="jev-1.13-free",
        key_env="AGENTQA_JEV_API_KEY",
        base_env="AGENTQA_JEV_BASE_URL",
        model_env="AGENTQA_JEV_MODEL",
        needs_session_header=False,
        label="OpenCode Zen System One",
    ),
    ProviderRoute.COMMANDCODE_CHAT: RouteSpec(
        route=ProviderRoute.COMMANDCODE_CHAT,
        family=CHAT_FAMILY,
        origin="https://api.commandcode.ai/provider/v1",
        path="/chat/completions",
        default_model="deepseek/deepseek-v4.1-flash",
        key_env="AGENTQA_CMD_API_KEY",
        base_env="AGENTQA_CMD_BASE_URL",
        model_env="AGENTQA_CMD_CHAT_MODEL",
        needs_session_header=False,
        label="Command Code chat",
    ),
    ProviderRoute.COMMANDCODE_SYSTEMONE: RouteSpec(
        route=ProviderRoute.COMMANDCODE_SYSTEMONE,
        family=SYSTEMONE_FAMILY,
        origin="https://api.commandcode.ai/provider/v1",
        path="/systemone",
        default_model="typesafe/jev",
        key_env="AGENTQA_CMD_API_KEY",
        base_env="AGENTQA_CMD_BASE_URL",
        model_env="AGENTQA_CMD_DECISION_MODEL",
        needs_session_header=False,
        label="Command Code System One",
    ),
}

MODEL_PAIRS: dict[str, tuple[ProviderRoute, ProviderRoute]] = {
    OPENCODE_PAIR: (ProviderRoute.OPENCODE_GO, ProviderRoute.OPENCODE_ZEN),
    COMMANDCODE_PAIR: (ProviderRoute.COMMANDCODE_CHAT, ProviderRoute.COMMANDCODE_SYSTEMONE),
}

DEFAULT_PAIR = OPENCODE_PAIR


def route_spec(route: ProviderRoute) -> RouteSpec:
    try:
        return ROUTE_CATALOG[route]
    except KeyError:
        raise ModelTransportError(ErrorCode.PERMISSION_DENIED, f"Route '{route.value}' chưa đăng ký") from None


def resolve_pair(name: str) -> tuple[ProviderRoute, ProviderRoute]:
    try:
        return MODEL_PAIRS[name]
    except KeyError:
        raise ModelTransportError(
            ErrorCode.INPUT_INVALID, f"Model pair '{name}' không hỗ trợ (chọn {sorted(MODEL_PAIRS)})"
        ) from None
