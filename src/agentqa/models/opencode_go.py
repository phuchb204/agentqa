from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from agentqa.contracts.canonical import digest_artifact_bytes
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    GenerationImagePart,
    GenerationMessage,
    GenerationRequest,
    GenerationResult,
    GenerationTextPart,
    OutputFormat,
    ProviderRoute,
    Usage,
)
from agentqa.contracts.ports import CallLedgerPort
from agentqa.contracts.values import JsonValue, SensitiveValue
from agentqa.models.retry import RetryController, TransportReply
from agentqa.models.usage import AttemptLedger, parse_provider_usage
from agentqa.models.wire import (
    GO_WIRE_VERSION,
    ImageLoader,
    ModelTransportError,
    authorization_header,
    classify_http_status,
    ensured_url,
    parse_json_object,
    user_agent,
)


@dataclass(frozen=True)
class GoReply:
    raw_text: str
    structured: dict[str, JsonValue] | None
    usage: Usage | None
    model_resolved: str | None


class GoChatAdapter:
    route = ProviderRoute.OPENCODE_GO
    schema_version = GO_WIRE_VERSION

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: SensitiveValue,
        session_id: str,
        client: httpx.AsyncClient | None = None,
        retry: RetryController | None = None,
        ledger: CallLedgerPort | None = None,
        image_loader: ImageLoader | None = None,
        structured_output: bool = False,
        timeout: float = 30.0,
        extra_body: dict[str, JsonValue] | None = None,
    ) -> None:
        self._url = ensured_url(self.route, base_url)
        self._model = model
        self._api_key = api_key
        self._session_id = session_id
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._retry = retry or RetryController()
        self._ledger = ledger
        self._image_loader = image_loader
        self._structured_output = structured_output
        self._extra_body = dict(extra_body or {})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        attempt_ledger = AttemptLedger(
            purpose=request.purpose,
            route=self.route,
            requested_model=self._model,
            session_id=self._session_id,
        )

        def record(attempt) -> None:
            attempt_ledger.record_attempt(self._ledger, attempt)

        result = await self._retry.run(lambda attempt_no: self._attempt(request, attempt_no), record_attempt=record)
        reply = result.value
        return GenerationResult(
            route=self.route,
            model=self._model,
            model_resolved=reply.model_resolved,
            raw_text=reply.raw_text,
            structured=reply.structured,
            usage=reply.usage,
        )

    async def _attempt(self, request: GenerationRequest, attempt_no: int) -> TransportReply[GoReply]:
        body = self._build_body(request)
        headers = self._headers()
        try:
            response = await self._client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as error:
            raise ModelTransportError(ErrorCode.PROVIDER_TIMEOUT, "Go request quá thời gian", retryable=True) from error
        except httpx.HTTPError as error:
            raise ModelTransportError(ErrorCode.PROVIDER_TIMEOUT, "Go transport lỗi", retryable=True) from error
        if response.status_code >= 300:
            raise classify_http_status(response.status_code, headers=response.headers)
        payload = _response_json(response)
        usage = parse_provider_usage(payload.get("usage"))
        model_resolved = payload.get("model") if isinstance(payload.get("model"), str) else None
        content = _message_content(payload)
        structured = None
        if request.output_format == OutputFormat.JSON_OBJECT:
            structured = parse_json_object(content)
        reply = GoReply(raw_text=content, structured=structured, usage=usage, model_resolved=model_resolved)
        return TransportReply(value=reply, usage=usage, resolved_model=model_resolved)

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": authorization_header(self._api_key.reveal()),
            "content-type": "application/json",
            "user-agent": user_agent(),
            "x-opencode-session": self._session_id,
        }

    def _build_body(self, request: GenerationRequest) -> dict[str, JsonValue]:
        body: dict[str, JsonValue] = dict(self._extra_body)
        body["model"] = self._model
        body["messages"] = [self._wire_message(message) for message in request.messages]
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.output_format == OutputFormat.JSON_OBJECT and self._structured_output:
            body["response_format"] = {"type": "json_object"}
        return body

    def _wire_message(self, message: GenerationMessage) -> dict[str, JsonValue]:
        text_parts = [part.text for part in message.parts if isinstance(part, GenerationTextPart)]
        image_parts = [part for part in message.parts if isinstance(part, GenerationImagePart)]
        if not image_parts:
            return {"role": message.role.value, "content": "\n".join(text_parts)}
        content: list[JsonValue] = [{"type": "text", "text": "\n".join(text_parts)}]
        for part in image_parts:
            content.append(self._image_content(part))
        return {"role": message.role.value, "content": content}

    def _image_content(self, part: GenerationImagePart) -> dict[str, JsonValue]:
        if self._image_loader is None:
            raise ModelTransportError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                "Route chưa có image loader được cấu hình",
            )
        try:
            payload = self._image_loader(part.ref)
        except (KeyError, OSError) as error:
            raise ModelTransportError(
                ErrorCode.CAPABILITY_UNAVAILABLE, f"Không đọc được image ref '{part.ref}'"
            ) from error
        if digest_artifact_bytes(payload.data) != part.sha256:
            raise ModelTransportError(ErrorCode.INPUT_INVALID, f"Image ref '{part.ref}' không khớp digest")
        encoded = base64.b64encode(payload.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{payload.media_type};base64,{encoded}"},
        }


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go response không phải JSON hợp lệ") from error
    if not isinstance(payload, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go response phải là JSON object")
    return payload


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go response thiếu choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go choice không hợp lệ")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go choice thiếu message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ModelTransportError(ErrorCode.PROVIDER_SCHEMA, "Go message content phải là chuỗi")
    return content
