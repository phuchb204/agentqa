from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from agentqa.contracts.models import GenerationRequest, GenerationResult, ProviderRoute, Usage


def _payload(request: GenerationRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        for part in message.parts:
            text = getattr(part, "text", None)
            if not text:
                continue
            try:
                loaded = json.loads(text)
            except ValueError:
                continue
            if isinstance(loaded, dict) and "goal" in loaded:
                return loaded
    return {}


def _source_defs(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources") or []
    if not sources:
        return {
            "create_item": {
                "source_content_digest": "1b37b1a900f62fb258ea067be0549ac1521129604f18dc316566c10fefe057d0",
                "anchor": {"type": "section", "value": "create-item"},
                "quote_digest": "99030afd9733cdd28fd467f6139c23619d4846791e829a44bb789867b2ee8aa3",
                "provenance": "user",
            }
        }
    source = sources[0]
    segments = source.get("segments") or []
    segment = segments[0] if segments else {"anchor": {"type": "section", "value": "body"}, "text": ""}
    text = str(segment.get("text", ""))
    return {
        "create_item": {
            "source_content_digest": str(source.get("file_digest", "a" * 64)),
            "anchor": segment.get("anchor", {"type": "section", "value": "body"}),
            "quote_digest": sha256(text.encode("utf-8")).hexdigest(),
            "provenance": "user",
        }
    }


def authored_taskboard_case(payload: dict[str, Any]) -> dict[str, Any]:
    requirement_keys = payload.get("requirement_keys") or ["create_item"]
    return {
        "schema_version": "case/1",
        "logical_key": "authored_create_item",
        "title": "Tạo việc mới từ yêu cầu",
        "goal": str(payload.get("goal") or "Tạo một việc mới và xác nhận nó xuất hiện đúng một lần"),
        "requirements": list(requirement_keys),
        "source_defs": _source_defs(payload),
        "postcondition_defs": {
            "authenticated": {
                "classification": "process",
                "condition": {
                    "kind": "comparison",
                    "comparator": "visible",
                    "target": {"intent": "task_page_heading", "role": "heading", "name": "Danh sách việc"},
                    "expected": {"kind": "literal", "value": True},
                },
            },
            "item_created": {
                "classification": "process",
                "condition": {
                    "kind": "comparison",
                    "comparator": "count_equals",
                    "target": {
                        "intent": "created_item_row",
                        "role": "listitem",
                        "entity_scope": {
                            "field": "text",
                            "value": {"kind": "parameter", "name": "item_name", "type": "string"},
                        },
                    },
                    "expected": {"kind": "literal", "value": 1},
                },
            },
        },
        "parameter_defs": {"item_name": {"type": "string", "required": True}},
        "fixture_refs": ["taskboard@1"],
        "nodes": [
            {
                "id": "open_login",
                "kind": "action",
                "operation": "navigate",
                "value": {"kind": "literal", "value": "/login"},
                "side_effect": "read",
            },
            {
                "id": "username",
                "kind": "action",
                "operation": "fill",
                "target": {"intent": "login_username", "role": "textbox", "name": "Tài khoản"},
                "value": {"kind": "secret", "credential_ref": "taskboard.alice.username"},
                "side_effect": "reversible",
            },
            {
                "id": "password",
                "kind": "action",
                "operation": "fill",
                "target": {"intent": "login_password", "locators": [{"kind": "label", "value": "Mật khẩu"}]},
                "value": {"kind": "secret", "credential_ref": "taskboard.alice.password"},
                "side_effect": "reversible",
            },
            {
                "id": "sign_in",
                "kind": "action",
                "operation": "click",
                "target": {"intent": "login_submit", "role": "button", "name": "Đăng nhập"},
                "side_effect": "external_write",
                "postconditions": ["authenticated"],
            },
            {
                "id": "item_name",
                "kind": "action",
                "operation": "fill",
                "target": {"intent": "new_item", "role": "textbox", "name": "Việc mới"},
                "value": {"kind": "parameter", "name": "item_name", "type": "string"},
                "side_effect": "reversible",
            },
            {
                "id": "add_item",
                "kind": "action",
                "operation": "click",
                "target": {"intent": "create_item", "role": "button", "name": "Thêm việc"},
                "side_effect": "external_write",
                "postconditions": ["item_created"],
            },
            {
                "id": "settle_wait",
                "kind": "action",
                "operation": "wait",
                "value": {"kind": "literal", "value": payload.get("settle_seconds", 2)},
                "side_effect": "read",
            },
            {
                "id": "result",
                "kind": "checkpoint",
                "assertions": [
                    {
                        "id": "item_exists_once",
                        "required": True,
                        "target": {
                            "intent": "created_item_row",
                            "role": "listitem",
                            "entity_scope": {
                                "field": "text",
                                "value": {"kind": "parameter", "name": "item_name", "type": "string"},
                            },
                        },
                        "comparator": "count_equals",
                        "expected": {"kind": "literal", "value": 1},
                        "source_refs": ["create_item"],
                    }
                ],
            },
        ],
        "completion": {"required_nodes": ["add_item", "result"], "required_assertions": ["item_exists_once"]},
    }


class HarnessAuthoringGo:
    route = ProviderRoute.OPENCODE_GO
    schema_version = "opencode-go-chat/1"

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        payload = _payload(request)
        case = authored_taskboard_case(payload)
        requirement_keys = payload.get("requirement_keys") or ["create_item"]
        structured = {
            "proposals": [
                {
                    "title": "Tạo việc mới và xác nhận xuất hiện một lần",
                    "case_kind": "positive",
                    "requirement_keys": list(requirement_keys),
                    "case": case,
                    "provenance": [{"path": "source_defs.create_item", "source": "user"}],
                }
            ]
        }
        return GenerationResult(
            route=self.route,
            model="deepseek-v4.1-flash",
            model_resolved="deepseek-v4.1-flash",
            raw_text=json.dumps(structured, ensure_ascii=False),
            structured=structured,
            usage=Usage(input_tokens=200, output_tokens=120),
        )
