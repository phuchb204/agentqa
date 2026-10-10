from __future__ import annotations

import json
from typing import Any

from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import GenerationRequest, GenerationResult, ProviderRoute, Usage
from agentqa.models.wire import ModelTransportError

FAKE_GO_MODEL = "deepseek-v4.1-flash"


class ScriptedAuthoringGo:
    route = ProviderRoute.OPENCODE_GO
    schema_version = "opencode-go-chat/1"

    def __init__(self, reply: dict[str, Any] | None = None) -> None:
        self.reply = reply
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if self.reply is None:
            raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "authoring reply chưa được script")
        return GenerationResult(
            route=self.route,
            model=FAKE_GO_MODEL,
            model_resolved=FAKE_GO_MODEL,
            raw_text=json.dumps(self.reply, ensure_ascii=False),
            structured=self.reply,
            usage=Usage(input_tokens=120, output_tokens=80),
        )


def authored_case(
    logical_key: str = "authored_case",
    *,
    source_name: str = "flow_source",
    source_digest: str = "a" * 64,
    quote_digest: str = "b" * 64,
    inferred: bool = False,
    expected: str = "/done",
) -> dict[str, Any]:
    return {
        "schema_version": "case/1",
        "logical_key": logical_key,
        "title": "Ca được đề xuất",
        "goal": "Xác nhận đường dẫn hoàn tất",
        "requirements": ["flow_requirement"],
        "source_defs": {
            source_name: {
                "source_content_digest": source_digest,
                "anchor": {"type": "section", "value": "flow"},
                "quote_digest": quote_digest,
                "provenance": "inferred" if inferred else "user",
            }
        },
        "nodes": [
            {
                "id": "open",
                "kind": "action",
                "operation": "navigate",
                "value": {"kind": "literal", "value": "/start"},
                "side_effect": "read",
            },
            {
                "id": "check",
                "kind": "checkpoint",
                "assertions": [
                    {
                        "id": "path_reached",
                        "required": True,
                        "comparator": "url_path_equals",
                        "expected": {"kind": "literal", "value": expected},
                        "source_refs": [source_name],
                    }
                ],
            },
        ],
        "completion": {"required_nodes": ["open", "check"], "required_assertions": ["path_reached"]},
    }


def proposal_payload(
    *,
    case: dict[str, Any],
    kind: str = "positive",
    title: str = "Đề xuất ca",
    requirement_keys: list[str] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "proposals": [
            {
                "title": title,
                "case_kind": kind,
                "requirement_keys": requirement_keys if requirement_keys is not None else ["flow_requirement"],
                "case": case,
                "provenance": provenance
                if provenance is not None
                else [{"path": "source_defs.flow_source", "source": "user"}],
            }
        ]
    }


__all__ = ["FAKE_GO_MODEL", "ScriptedAuthoringGo", "authored_case", "proposal_payload"]
