from __future__ import annotations

from agentqa.contracts.models import ProviderRoute
from agentqa.contracts.values import JsonValue, SensitiveValue
from agentqa.models.opencode_go import GoChatAdapter
from agentqa.models.opencode_zen import ZenSystemOneAdapter
from agentqa.models.wire import (
    COMMANDCODE_CHAT_WIRE_VERSION,
    COMMANDCODE_SYSTEMONE_WIRE_VERSION,
    ImageLoader,
)


class CommandCodeChatAdapter(GoChatAdapter):
    route = ProviderRoute.COMMANDCODE_CHAT
    schema_version = COMMANDCODE_CHAT_WIRE_VERSION

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: SensitiveValue,
        session_id: str = "",
        client=None,
        retry=None,
        ledger=None,
        image_loader: ImageLoader | None = None,
        structured_output: bool = False,
        timeout: float = 30.0,
        extra_body: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=api_key,
            session_id=session_id,
            client=client,
            retry=retry,
            ledger=ledger,
            image_loader=image_loader,
            structured_output=structured_output,
            timeout=timeout,
            extra_body=extra_body,
            send_session_header=False,
        )


class CommandCodeSystemOneAdapter(ZenSystemOneAdapter):
    route = ProviderRoute.COMMANDCODE_SYSTEMONE
    schema_version = COMMANDCODE_SYSTEMONE_WIRE_VERSION
