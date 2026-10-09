from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from tools import model_conformance as mc

from agentqa.contracts.capabilities import CapabilityKind, CapabilityReceipt, CapabilityStatus
from agentqa.contracts.errors import ErrorCode
from agentqa.contracts.models import ProviderRoute
from agentqa.platform.models.capabilities import (
    CapabilityReceiptStore,
    ReceiptError,
    migrate_receipt_document,
    parse_receipt,
    route_epoch,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def valid_document(**overrides) -> dict:
    document = {
        "schema_version": "capability-receipt/1",
        "receipt_id": str(uuid4()),
        "route": "opencode_go",
        "model_requested": "deepseek-v4.1-flash",
        "model_resolved": "deepseek-v4.1-flash",
        "adapter_schema_version": "opencode-go-chat/1",
        "request_digest": "a" * 64,
        "result_digest": "b" * 64,
        "capabilities": {"text": "verified", "image": "verified"},
        "version_identity": "unverified",
        "route_epoch": "epoch-1",
        "verified_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "deployment_version": None,
        "blocked_reason": None,
    }
    document.update(overrides)
    return document


def receipt(**overrides) -> CapabilityReceipt:
    return parse_receipt(valid_document(**overrides))


def test_parse_valid_receipt_round_trip() -> None:
    parsed = receipt()
    assert parsed.route is ProviderRoute.OPENCODE_GO
    assert parsed.capability_status(CapabilityKind.TEXT) is CapabilityStatus.VERIFIED
    assert parsed.version_identity == "unverified"
    assert parsed.image_ready_at(NOW) is True


def test_parse_rejects_unknown_schema_version() -> None:
    with pytest.raises(ReceiptError) as excinfo:
        parse_receipt(valid_document(schema_version="capability-receipt/99"))
    assert excinfo.value.code is ErrorCode.UNSUPPORTED_SCHEMA_VERSION
    assert migrate_receipt_document(valid_document())["schema_version"] == "capability-receipt/1"


def test_parse_rejects_bad_digest_and_missing_reason() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt(valid_document(request_digest="not-hex"))
    with pytest.raises(ReceiptError):
        parse_receipt(valid_document(capabilities={"image": "blocked"}, blocked_reason=None))


def test_parse_rejects_secret_fields_in_document() -> None:
    document = valid_document()
    document["api_key"] = "sk-leak"
    with pytest.raises(ReceiptError) as excinfo:
        parse_receipt(document)
    assert excinfo.value.code is ErrorCode.SECRET_SERIALIZATION


def test_store_save_load_latest_and_expiry(tmp_path: Path) -> None:
    store = CapabilityReceiptStore(tmp_path)
    expired = receipt(
        receipt_id=str(uuid4()),
        verified_at=(NOW - timedelta(days=30)).isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
    )
    fresh = receipt(receipt_id=str(uuid4()), verified_at=NOW.isoformat())
    store.save(expired)
    store.save(fresh)
    assert len(store.load_all()) == 2
    latest = store.latest(route=ProviderRoute.OPENCODE_GO, model="deepseek-v4.1-flash")
    assert latest is not None and latest.receipt_id == fresh.receipt_id
    status = store.status(
        route=ProviderRoute.OPENCODE_GO,
        model="deepseek-v4.1-flash",
        kind=CapabilityKind.TEXT,
        now=NOW,
    )
    assert status is CapabilityStatus.VERIFIED
    expired_status = store.image_gate(
        route=ProviderRoute.OPENCODE_GO,
        model="deepseek-v4.1-flash",
        now=NOW + timedelta(days=30),
    )
    assert expired_status is CapabilityStatus.BLOCKED
    unknown_status = store.image_gate(route=ProviderRoute.OPENCODE_ZEN, model="jev-1.13-free", now=NOW)
    assert unknown_status is CapabilityStatus.UNVERIFIED


def test_route_epoch_is_stable_per_day_and_changes() -> None:
    first = route_epoch(ProviderRoute.OPENCODE_GO, "deepseek-v4.1-flash", day="2026-10-09")
    second = route_epoch(ProviderRoute.OPENCODE_GO, "deepseek-v4.1-flash", day="2026-10-09")
    other = route_epoch(ProviderRoute.OPENCODE_GO, "deepseek-v4.1-flash", day="2026-10-10")
    assert first == second
    assert first != other


def test_offline_validate_rejects_unlisted_route_and_missing_budgets(capsys) -> None:
    with pytest.raises(SystemExit) as wrong_model:
        mc.validate_offline(
            mc.build_parser().parse_args(
                [
                    "--provider",
                    "opencode_go",
                    "--model",
                    "gpt-4",
                    "--max-calls",
                    "2",
                    "--max-output-tokens",
                    "100",
                ]
            )
        )
    assert wrong_model.value.code == 64
    assert "model_not_pinned" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        mc.validate_offline(mc.build_parser().parse_args(["--provider", "opencode_zen", "--model", "jev-1.13-free"]))

    with pytest.raises(SystemExit):
        mc.validate_offline(
            mc.build_parser().parse_args(
                ["--provider", "opencode_go", "--model", "deepseek-v4.1-flash", "--max-calls", "2"]
            )
        )


def test_offline_validate_accepts_pinned_combos() -> None:
    zen = mc.validate_offline(
        mc.build_parser().parse_args(["--provider", "opencode_zen", "--model", "jev-1.13-free", "--max-calls", "4"])
    )
    assert zen["status"] == "validated_offline"
    assert zen["adapter_schema_version"] == "opencode-zen-systemone/1"
    go = mc.validate_offline(
        mc.build_parser().parse_args(
            [
                "--provider",
                "opencode_go",
                "--model",
                "deepseek-v4.1-flash",
                "--max-calls",
                "4",
                "--max-output-tokens",
                "2048",
            ]
        )
    )
    assert go["status"] == "validated_offline"


def test_main_without_live_is_offline_validate(capsys) -> None:
    code = mc.main(["--provider", "opencode_zen", "--model", "jev-1.13-free", "--max-calls", "4"])
    assert code == 0
    assert "validated_offline" in capsys.readouterr().out


def marker_transport(script: list[dict]) -> httpx.MockTransport:
    pending = list(script)

    def handler(request: httpx.Request) -> httpx.Response:
        assert pending, "transport script exhausted"
        item = pending.pop(0)
        if item.get("status", 200) >= 400:
            return httpx.Response(item["status"], json={"error": "scripted"})
        return httpx.Response(200, json=item["json"])

    return httpx.MockTransport(handler)


def go_args(tmp_path: Path, **overrides) -> list[str]:
    values = {
        "--provider": "opencode_go",
        "--model": "deepseek-v4.1-flash",
        "--live": None,
        "--max-calls": "4",
        "--max-output-tokens": "512",
        "--receipts-dir": str(tmp_path),
    }
    values.update(overrides)
    argv: list[str] = []
    for key, value in values.items():
        argv.append(key)
        if value is not None:
            argv.append(value)
    return argv


def go_response(content: str, input_tokens: int, output_tokens: int) -> dict:
    return {
        "model": "deepseek-v4.1-flash",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


def go_success_script() -> list[dict]:
    return [
        {"json": go_response("OK", 5, 1)},
        {"json": go_response('{"ok": true}', 6, 2)},
        {"json": go_response('{"squares": 3}', 9, 3)},
    ]


@pytest.mark.asyncio
async def test_live_go_happy_path_writes_sanitized_receipt(tmp_path: Path, capsys) -> None:
    args = mc.build_parser().parse_args(go_args(tmp_path))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_LLM_API_KEY": "sk-canary-conformance"},
        transport=marker_transport(go_success_script()),
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    receipt_path = Path(output["receipt"])
    text = receipt_path.read_text(encoding="utf-8")
    assert "sk-canary-conformance" not in text
    document = json.loads(text)
    assert document["route"] == "opencode_go"
    assert document["version_identity"] == "unverified"
    assert len(document["request_digest"]) == 64
    assert len(document["result_digest"]) == 64
    assert document["capabilities"]["image"] == "verified"
    assert document["capabilities"]["structured_output"] == "verified"
    assert document["capabilities"]["session"] == "verified"
    assert document["capabilities"]["usage"] == "verified"
    assert document["capabilities"]["cache"] == "unverified"
    assert document["blocked_reason"] is None
    parsed = parse_receipt(document)
    assert parsed.image_ready_at(NOW) is True


@pytest.mark.asyncio
async def test_live_go_image_marker_mismatch_blocks_image(tmp_path: Path, capsys) -> None:
    script = go_success_script()
    script[2] = {"json": go_response('{"squares": 2}', 9, 3)}
    args = mc.build_parser().parse_args(go_args(tmp_path))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_LLM_API_KEY": "sk-canary"},
        transport=marker_transport(script),
    )
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert document["capabilities"]["image"] == "blocked"
    assert "image_marker_mismatch" in document["blocked_reason"]
    assert document["route"] == "opencode_go"


@pytest.mark.asyncio
async def test_live_go_call_budget_stops_second_probe(tmp_path: Path, capsys) -> None:
    args = mc.build_parser().parse_args(go_args(tmp_path, **{"--max-calls": "1"}))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_LLM_API_KEY": "sk-canary"},
        transport=marker_transport(go_success_script()),
    )
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert "call_budget_exceeded" in document["blocked_reason"]


@pytest.mark.asyncio
async def test_live_go_auth_failure_saved_as_blocked_reason(tmp_path: Path, capsys) -> None:
    script = [{"status": 401}]
    args = mc.build_parser().parse_args(go_args(tmp_path))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_LLM_API_KEY": "sk-canary"},
        transport=marker_transport(script),
    )
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert "provider_auth" in document["blocked_reason"]
    assert document["model_requested"] == "deepseek-v4.1-flash"


@pytest.mark.asyncio
async def test_live_missing_key_writes_blocked_receipt_without_transport(tmp_path: Path, capsys) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError("khong duoc goi transport khi thieu key")

    args = mc.build_parser().parse_args(go_args(tmp_path))
    exit_code = await mc.run_live(args, env={}, transport=httpx.MockTransport(handler))
    assert exit_code == 2
    assert called is False
    output = json.loads(capsys.readouterr().out)
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert "missing_credential_env" in document["blocked_reason"]


def zen_success_payload() -> dict:
    return {
        "model": "jev-1.13-free",
        "answers": {
            "tone": {
                "type": "choice",
                "choice": "ok",
                "confidence": 0.9,
                "probabilities": {"ok": 0.9, "alert": 0.1},
            },
            "complete": {"type": "noul", "noul": 0.9},
            "urgency": {
                "type": "score",
                "score": 1.2,
                "confidence": 0.8,
                "legend": {"0": "thấp", "1": "trung bình", "2": "cao"},
                "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
            },
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def zen_args(tmp_path: Path) -> list[str]:
    return [
        "--provider",
        "opencode_zen",
        "--model",
        "jev-1.13-free",
        "--live",
        "--max-calls",
        "4",
        "--receipts-dir",
        str(tmp_path),
    ]


@pytest.mark.asyncio
async def test_live_zen_happy_path_marks_text_only_capabilities(tmp_path: Path, capsys) -> None:
    args = mc.build_parser().parse_args(zen_args(tmp_path))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_JEV_API_KEY": "sk-canary-zen"},
        transport=marker_transport([{"json": zen_success_payload()}]),
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert document["capabilities"]["text"] == "verified"
    assert document["capabilities"]["structured_output"] == "verified"
    assert document["capabilities"]["usage"] == "verified"
    assert document["capabilities"]["image"] == "unsupported"
    assert document["capabilities"]["cache"] == "unsupported"
    assert document["blocked_reason"] is not None


@pytest.mark.asyncio
async def test_live_zen_missing_answer_is_blocked(tmp_path: Path, capsys) -> None:
    payload = zen_success_payload()
    payload["answers"].pop("urgency")
    args = mc.build_parser().parse_args(zen_args(tmp_path))
    exit_code = await mc.run_live(
        args,
        env={"AGENTQA_JEV_API_KEY": "sk-canary-zen"},
        transport=marker_transport([{"json": payload}]),
    )
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    document = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
    assert document["capabilities"]["text"] == "blocked"
    assert "provider_schema" in document["blocked_reason"]


def test_marker_image_is_visual_not_text() -> None:
    data = mc.marker_image_bytes()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    red_pixels = 0
    for x in range(image.width):
        for y in range(image.height):
            r, g, b = image.getpixel((x, y))
            if r > 180 and g < 80 and b < 80:
                red_pixels += 1
    assert red_pixels > 1000
    assert mc.MARKER_SQUARES == 3
    assert len(mc.marker_image_digest()) == 64
