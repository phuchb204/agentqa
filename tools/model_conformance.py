from __future__ import annotations

import argparse
import io
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from agentqa.contracts.capabilities import (
    CapabilityKind,
    CapabilityReceipt,
    CapabilityStatus,
)
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import (
    ChoiceQuestion,
    DecisionRequest,
    GenerationMessage,
    GenerationMessageRole,
    GenerationRequest,
    GenerationTextPart,
    MessagePurpose,
    NoulQuestion,
    OutputFormat,
    ProviderRoute,
    ScoreQuestion,
)
from agentqa.contracts.values import SensitiveValue
from agentqa.models.opencode_go import GoChatAdapter
from agentqa.models.opencode_zen import ZenSystemOneAdapter
from agentqa.models.retry import RetryController, RetryPolicy
from agentqa.models.wire import (
    GO_WIRE_VERSION,
    ZEN_WIRE_VERSION,
    ImagePayload,
    ModelTransportError,
    user_agent,
)
from agentqa.platform.models.capabilities import (
    CapabilityReceiptStore,
    request_digest,
    result_digest,
    route_epoch,
)

ROUTE_MODELS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_ZEN: "jev-1.13-free",
    ProviderRoute.OPENCODE_GO: "deepseek-v4.1-flash",
}

ROUTE_BASE_URLS: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_ZEN: "https://opencode.ai/zen/v1",
    ProviderRoute.OPENCODE_GO: "https://opencode.ai/zen/go/v1",
}

ROUTE_KEY_ENV: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_ZEN: "AGENTQA_JEV_API_KEY",
    ProviderRoute.OPENCODE_GO: "AGENTQA_LLM_API_KEY",
}

ROUTE_ADAPTER_SCHEMA: dict[ProviderRoute, str] = {
    ProviderRoute.OPENCODE_ZEN: ZEN_WIRE_VERSION,
    ProviderRoute.OPENCODE_GO: GO_WIRE_VERSION,
}

DEFAULT_RECEIPTS_DIR = "artifacts/model-capabilities"
DEFAULT_MAX_REQUEST_BYTES = 65_536
DEFAULT_EXPIRY_DAYS = 7
MARKER_SQUARES = 3
FORBIDDEN_KEYS = ("api_key", "authorization", "token", "password", "secret", "bearer")


class BudgetError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


GLOBAL_ERROR_CODES = frozenset(
    {
        ErrorCode.PROVIDER_AUTH,
        ErrorCode.PROVIDER_QUOTA,
        ErrorCode.PROVIDER_RATE_LIMIT,
        ErrorCode.PROVIDER_TIMEOUT,
        ErrorCode.PERMISSION_DENIED,
    }
)


class SanitizingSink:
    def __init__(self, secrets: list[str] | None = None) -> None:
        self._secrets = [value for value in (secrets or []) if value]

    def sanitize(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            cleaned: dict[str, Any] = {}
            for key, value in payload.items():
                if any(forbidden in str(key).lower() for forbidden in FORBIDDEN_KEYS):
                    continue
                cleaned[str(key)] = self.sanitize(value)
            return cleaned
        if isinstance(payload, (list, tuple)):
            return [self.sanitize(item) for item in payload]
        if isinstance(payload, str):
            redacted = payload
            for secret in self._secrets:
                redacted = redacted.replace(secret, "[REDACTED]")
            return redacted
        return payload

    def digest(self, payload: Any) -> str:
        return sha256(
            json.dumps(self.sanitize(payload), ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()


class CallBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.calls = 0

    def consume(self, label: str) -> None:
        self.calls += 1
        if self.calls > self.max_calls:
            raise BudgetError(f"call_budget_exceeded:{label}")


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()
        self.headers: list[dict[str, str]] = []
        self.request_bytes: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.headers.append({key.lower(): value for key, value in request.headers.items()})
        self.request_bytes.append(len(request.content))
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass
class ProbeOutcome:
    capabilities: dict[CapabilityKind, CapabilityStatus] = field(default_factory=dict)
    reasons: dict[CapabilityKind, str] = field(default_factory=dict)
    request_payloads: list[Any] = field(default_factory=list)
    result_payloads: list[Any] = field(default_factory=list)
    model_resolved: str | None = None


def marker_image_bytes() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (240, 120), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for index in range(MARKER_SQUARES):
        x = 20 + index * 70
        draw.rectangle([x, 30, x + 40, 90], fill=(220, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def marker_image_digest() -> str:
    return sha256(marker_image_bytes()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model_conformance",
        description="Conformance hai phase cho đúng hai route model; mặc định offline validate",
    )
    parser.add_argument("--provider", required=True, choices=[route.value for route in ROUTE_MODELS])
    parser.add_argument("--model", required=True)
    parser.add_argument("--live", action="store_true", help="bắt buộc để gọi provider thật")
    parser.add_argument("--max-calls", type=int, default=0, help="call budget bắt buộc khi --live")
    parser.add_argument("--max-output-tokens", type=int, default=0)
    parser.add_argument("--max-request-bytes", type=int, default=DEFAULT_MAX_REQUEST_BYTES)
    parser.add_argument("--receipts-dir", default=DEFAULT_RECEIPTS_DIR)
    parser.add_argument("--expiry-days", type=int, default=DEFAULT_EXPIRY_DAYS)
    return parser


def validate_offline(args: argparse.Namespace) -> dict[str, Any]:
    route = ProviderRoute(args.provider)
    expected_model = ROUTE_MODELS[route]
    if args.model != expected_model:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": "model_not_pinned",
                    "expected": expected_model,
                    "requested": args.model,
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(64)
    if args.max_calls <= 0:
        print(json.dumps({"status": "rejected", "reason": "missing_call_budget"}, ensure_ascii=False))
        raise SystemExit(64)
    if route is ProviderRoute.OPENCODE_GO and args.max_output_tokens <= 0:
        print(json.dumps({"status": "rejected", "reason": "missing_output_budget"}, ensure_ascii=False))
        raise SystemExit(64)
    if args.max_request_bytes <= 0:
        print(json.dumps({"status": "rejected", "reason": "missing_request_budget"}, ensure_ascii=False))
        raise SystemExit(64)
    return {
        "status": "validated_offline",
        "provider": route.value,
        "model": expected_model,
        "max_calls": args.max_calls,
        "max_output_tokens": args.max_output_tokens,
        "max_request_bytes": args.max_request_bytes,
        "adapter_schema_version": ROUTE_ADAPTER_SCHEMA[route],
    }


async def run_live(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    environment = env if env is not None else dict(os.environ)
    route = ProviderRoute(args.provider)
    summary = validate_offline(args)
    sink = SanitizingSink([environment.get(ROUTE_KEY_ENV[route], "")])
    budget = CallBudget(args.max_calls)
    recording = RecordingTransport(transport)
    client = httpx.AsyncClient(transport=recording, follow_redirects=False, timeout=60.0)
    store = CapabilityReceiptStore(Path(args.receipts_dir))
    key = environment.get(ROUTE_KEY_ENV[route], "")
    if not key:
        receipt = _blocked_receipt(
            route=route,
            args=args,
            sink=sink,
            reason=f"missing_credential_env:{ROUTE_KEY_ENV[route]}",
            summary=summary,
        )
        path = store.save(receipt)
        print(
            json.dumps(
                {"status": "blocked", "reason": receipt.blocked_reason, "receipt": str(path)},
                ensure_ascii=False,
            )
        )
        await client.aclose()
        return 2
    try:
        if route is ProviderRoute.OPENCODE_GO:
            outcome = await _probe_go(args, client, key, sink, budget, recording)
        else:
            outcome = await _probe_zen(args, client, key, sink, budget, recording)
    except (BudgetError, ModelTransportError) as error:
        reason = getattr(error, "reason", None) or getattr(error, "code", ErrorCode.PROVIDER_SCHEMA)
        receipt = _blocked_receipt(
            route=route,
            args=args,
            sink=sink,
            reason=str(reason),
            summary=summary,
        )
        path = store.save(receipt)
        print(
            json.dumps(
                {"status": "blocked", "reason": receipt.blocked_reason, "receipt": str(path)},
                ensure_ascii=False,
            )
        )
        await client.aclose()
        return 2
    receipt = _build_receipt(route=route, args=args, sink=sink, summary=summary, outcome=outcome)
    path = store.save(receipt)
    failed = [kind.value for kind, status in outcome.capabilities.items() if status is CapabilityStatus.BLOCKED]
    status = "verified" if not failed else "blocked"
    print(
        json.dumps(
            {
                "status": status,
                "receipt": str(path),
                "capabilities": {kind.value: value.value for kind, value in outcome.capabilities.items()},
                "blocked": failed,
            },
            ensure_ascii=False,
        )
    )
    await client.aclose()
    return 0 if not failed else 2


async def _probe_go(
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    key: str,
    sink: SanitizingSink,
    budget: CallBudget,
    recording: RecordingTransport,
) -> ProbeOutcome:
    outcome = ProbeOutcome()
    session_id = f"conformance-{uuid4().hex[:12]}"
    image = marker_image_bytes()
    loader_ref = "conformance-marker"
    image_part = {
        "ref": loader_ref,
        "media_type": "image/png",
        "sha256": marker_image_digest(),
    }
    adapter = GoChatAdapter(
        base_url=ROUTE_BASE_URLS[ProviderRoute.OPENCODE_GO],
        model=args.model,
        api_key=SensitiveValue(key),
        session_id=session_id,
        client=client,
        retry=RetryController(RetryPolicy(max_attempts=1)),
        image_loader=lambda ref: ImagePayload(media_type="image/png", data=image),
        structured_output=False,
        timeout=60.0,
    )
    text_request = GenerationRequest(
        purpose=MessagePurpose.CONFORMANCE,
        schema_name="conformance_text",
        schema_version="1",
        prompt_ref="conformance://go/text",
        max_output_tokens=args.max_output_tokens,
        output_format=OutputFormat.TEXT,
        messages=[
            GenerationMessage(
                role=GenerationMessageRole.USER,
                parts=[GenerationTextPart(text="Trả lời đúng một từ: OK")],
            )
        ],
    )
    budget.consume("go_text")
    _check_request_size(text_request, args, sink)
    text_result = await _probe_call("go_text", CapabilityKind.TEXT, outcome, adapter.generate(text_request))
    outcome.request_payloads.append(_request_view(text_request, sink))
    if text_result is not None:
        outcome.result_payloads.append({"text": text_result.raw_text})
        outcome.model_resolved = text_result.model_resolved
        outcome.capabilities[CapabilityKind.TEXT] = (
            CapabilityStatus.VERIFIED if (text_result.raw_text or "").strip() else CapabilityStatus.BLOCKED
        )
        if not (text_result.raw_text or "").strip():
            outcome.reasons[CapabilityKind.TEXT] = "empty_text_response"
        outcome.capabilities[CapabilityKind.USAGE] = (
            CapabilityStatus.VERIFIED if text_result.usage is not None else CapabilityStatus.UNVERIFIED
        )
        cached = text_result.usage.cached_tokens if text_result.usage is not None else None
        outcome.capabilities[CapabilityKind.CACHE] = (
            CapabilityStatus.VERIFIED if cached is not None else CapabilityStatus.UNVERIFIED
        )
    else:
        outcome.capabilities[CapabilityKind.USAGE] = CapabilityStatus.UNVERIFIED
        outcome.capabilities[CapabilityKind.CACHE] = CapabilityStatus.UNVERIFIED
    outcome.capabilities[CapabilityKind.SESSION] = _session_status(recording, session_id)

    json_request = text_request.model_copy(
        update={
            "purpose": MessagePurpose.CONFORMANCE,
            "schema_name": "conformance_json",
            "prompt_ref": "conformance://go/json",
            "output_format": OutputFormat.JSON_OBJECT,
            "messages": [
                GenerationMessage(
                    role=GenerationMessageRole.USER,
                    parts=[
                        GenerationTextPart(
                            text='Không giải thích, không markdown. Trả về đúng một JSON object: {"ok": true}'
                        )
                    ],
                )
            ],
        }
    )
    budget.consume("go_json")
    _check_request_size(json_request, args, sink)
    json_result = await _probe_call(
        "go_json", CapabilityKind.STRUCTURED_OUTPUT, outcome, adapter.generate(json_request)
    )
    outcome.request_payloads.append(_request_view(json_request, sink))
    if json_result is not None:
        outcome.result_payloads.append({"structured": json_result.structured})
        outcome.capabilities[CapabilityKind.STRUCTURED_OUTPUT] = (
            CapabilityStatus.VERIFIED
            if json_result.structured is not None and "ok" in json_result.structured
            else CapabilityStatus.BLOCKED
        )
        if outcome.capabilities[CapabilityKind.STRUCTURED_OUTPUT] is CapabilityStatus.BLOCKED:
            outcome.reasons[CapabilityKind.STRUCTURED_OUTPUT] = "json_object_not_returned"

    image_request = json_request.model_copy(
        update={
            "schema_name": "conformance_image",
            "prompt_ref": "conformance://go/image",
            "messages": [
                GenerationMessage(
                    role=GenerationMessageRole.USER,
                    parts=[
                        GenerationTextPart(
                            text='Đếm số hình vuông đỏ trong ảnh. Chỉ trả JSON, không markdown: {"squares": <số>}'
                        ),
                        _image_part_model(image_part),
                    ],
                )
            ],
        }
    )
    budget.consume("go_image")
    _check_request_size(image_request, args, sink)
    image_result = await _probe_call("go_image", CapabilityKind.IMAGE, outcome, adapter.generate(image_request))
    outcome.request_payloads.append(_request_view(image_request, sink))
    if image_result is not None:
        outcome.result_payloads.append({"structured": image_result.structured})
        squares = (image_result.structured or {}).get("squares")
        marker_ok = squares == MARKER_SQUARES
        outcome.capabilities[CapabilityKind.IMAGE] = (
            CapabilityStatus.VERIFIED if marker_ok else CapabilityStatus.BLOCKED
        )
        if not marker_ok:
            outcome.reasons[CapabilityKind.IMAGE] = f"image_marker_mismatch:{squares!r}"
    return outcome


async def _probe_zen(
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    key: str,
    sink: SanitizingSink,
    budget: CallBudget,
    recording: RecordingTransport,
) -> ProbeOutcome:
    outcome = ProbeOutcome()
    adapter = ZenSystemOneAdapter(
        base_url=ROUTE_BASE_URLS[ProviderRoute.OPENCODE_ZEN],
        model=args.model,
        api_key=SensitiveValue(key),
        client=client,
        retry=RetryController(RetryPolicy(max_attempts=1)),
        timeout=60.0,
    )
    request = DecisionRequest(
        state={"synthetic": "state cho conformance", "note": "không chứa dữ liệu thật"},
        questions=[
            ChoiceQuestion(
                question_id="tone",
                instructions="Chọn nhãn phù hợp",
                criteria={"ok": "nội dung bình thường", "alert": "nội dung cần chú ý"},
            ),
            NoulQuestion(question_id="complete", instructions="Nội dung đã đủ chưa?"),
            ScoreQuestion(
                question_id="urgency",
                instructions="Mức độ khẩn cấp",
                criteria=["thấp", "trung bình", "cao"],
            ),
        ],
    )
    budget.consume("zen_systemone")
    body_size = len(json.dumps({"state": request.state, "questions": len(request.questions)}, ensure_ascii=False))
    if body_size > args.max_request_bytes:
        raise BudgetError("request_budget_exceeded:zen_systemone")
    result = await _probe_call("zen_systemone", CapabilityKind.TEXT, outcome, adapter.decide(request))
    outcome.request_payloads.append(
        sink.sanitize({"questions": [question.question_id for question in request.questions]})
    )
    if result is not None:
        outcome.result_payloads.append(
            {"answers": {key: value.model_dump(mode="json") for key, value in result.answers.items()}}
        )
        outcome.model_resolved = result.model
        expected_ids = {question.question_id for question in request.questions}
        answers_ok = set(result.answers) == expected_ids
        outcome.capabilities[CapabilityKind.TEXT] = (
            CapabilityStatus.VERIFIED if answers_ok else CapabilityStatus.BLOCKED
        )
        if not answers_ok:
            outcome.reasons[CapabilityKind.TEXT] = "answers_not_keyed_by_question_ids"
        outcome.capabilities[CapabilityKind.STRUCTURED_OUTPUT] = (
            CapabilityStatus.VERIFIED if answers_ok else CapabilityStatus.BLOCKED
        )
        if not answers_ok:
            outcome.reasons[CapabilityKind.STRUCTURED_OUTPUT] = "answers_not_keyed_by_question_ids"
        outcome.capabilities[CapabilityKind.USAGE] = (
            CapabilityStatus.VERIFIED if result.usage is not None else CapabilityStatus.UNVERIFIED
        )
    else:
        outcome.capabilities[CapabilityKind.STRUCTURED_OUTPUT] = CapabilityStatus.BLOCKED
        outcome.reasons[CapabilityKind.STRUCTURED_OUTPUT] = outcome.reasons.get(
            CapabilityKind.TEXT, "provider_schema:zen_systemone"
        )
        outcome.capabilities[CapabilityKind.USAGE] = CapabilityStatus.UNVERIFIED
    outcome.capabilities[CapabilityKind.CACHE] = CapabilityStatus.UNSUPPORTED
    outcome.reasons[CapabilityKind.CACHE] = "zen_khong_co_cache_semantics"
    outcome.capabilities[CapabilityKind.IMAGE] = CapabilityStatus.UNSUPPORTED
    outcome.reasons[CapabilityKind.IMAGE] = "zen_systemone_text_only"
    outcome.capabilities[CapabilityKind.SESSION] = CapabilityStatus.UNSUPPORTED
    outcome.reasons[CapabilityKind.SESSION] = "zen_khong_dung_go_session"
    return outcome


async def _probe_call(label: str, capability: CapabilityKind, outcome: ProbeOutcome, coroutine):
    try:
        return await coroutine
    except ModelTransportError as error:
        if error.code in GLOBAL_ERROR_CODES:
            raise
        outcome.capabilities[capability] = CapabilityStatus.BLOCKED
        outcome.reasons[capability] = f"{error.code.value}:{label}:{str(error)[:80]}"
        return None


def _session_status(recording: RecordingTransport, session_id: str) -> CapabilityStatus:
    if not recording.headers:
        return CapabilityStatus.BLOCKED
    sent = all(header.get("x-opencode-session") == session_id for header in recording.headers)
    agents = all(header.get("user-agent", "").startswith("AgentQA/") for header in recording.headers)
    if sent and agents and user_agent().startswith("AgentQA/"):
        return CapabilityStatus.VERIFIED
    return CapabilityStatus.BLOCKED


def _request_view(request: GenerationRequest, sink: SanitizingSink) -> Any:
    return sink.sanitize(
        {
            "purpose": request.purpose.value,
            "schema_name": request.schema_name,
            "output_format": request.output_format.value,
            "prompt_ref": request.prompt_ref,
            "max_output_tokens": request.max_output_tokens,
            "messages": [
                {
                    "role": message.role.value,
                    "parts": [
                        {"kind": part.kind, "text": getattr(part, "text", None), "ref": getattr(part, "ref", None)}
                        for part in message.parts
                    ],
                }
                for message in request.messages
            ],
        }
    )


def _check_request_size(request: GenerationRequest, args: argparse.Namespace, sink: SanitizingSink) -> None:
    size = len(json.dumps(_request_view(request, sink), ensure_ascii=False).encode())
    if size > args.max_request_bytes:
        raise BudgetError(f"request_budget_exceeded:{request.schema_name}")


def _image_part_model(image_part: dict):
    from agentqa.contracts.models import GenerationImagePart

    return GenerationImagePart(**image_part)


def _build_receipt(
    *,
    route: ProviderRoute,
    args: argparse.Namespace,
    sink: SanitizingSink,
    summary: dict[str, Any],
    outcome: ProbeOutcome,
) -> CapabilityReceipt:
    now = datetime.now(UTC)
    blocked_reason = None
    for kind, status in outcome.capabilities.items():
        if status in (CapabilityStatus.BLOCKED, CapabilityStatus.UNSUPPORTED):
            blocked_reason = outcome.reasons.get(kind, f"{kind.value}_{status.value}")
            break
    return CapabilityReceipt(
        receipt_id=uuid4(),
        route=route,
        model_requested=args.model,
        model_resolved=outcome.model_resolved,
        adapter_schema_version=summary["adapter_schema_version"],
        request_digest=sink.digest(outcome.request_payloads),
        result_digest=sink.digest(outcome.result_payloads),
        capabilities=dict(outcome.capabilities),
        version_identity="unverified",
        route_epoch=route_epoch(route, args.model),
        verified_at=now,
        expires_at=now + timedelta(days=args.expiry_days),
        blocked_reason=blocked_reason,
    )


def _blocked_receipt(
    *,
    route: ProviderRoute,
    args: argparse.Namespace,
    sink: SanitizingSink,
    reason: str,
    summary: dict[str, Any],
) -> CapabilityReceipt:
    now = datetime.now(UTC)
    return CapabilityReceipt(
        receipt_id=uuid4(),
        route=route,
        model_requested=args.model,
        model_resolved=None,
        adapter_schema_version=summary["adapter_schema_version"],
        request_digest=request_digest({"phase": "blocked", "reason": reason}),
        result_digest=result_digest({"phase": "blocked"}),
        capabilities={CapabilityKind.TEXT: CapabilityStatus.BLOCKED},
        version_identity="unverified",
        route_epoch=route_epoch(route, args.model),
        verified_at=now,
        expires_at=now + timedelta(days=args.expiry_days),
        blocked_reason=reason,
    )


def main(argv: list[str] | None = None) -> int:
    import asyncio

    args = build_parser().parse_args(argv)
    if not args.live:
        summary = validate_offline(args)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    return asyncio.run(run_live(args))


if __name__ == "__main__":
    sys.exit(main())
