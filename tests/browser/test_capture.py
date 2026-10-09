from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image, ImageDraw

from agentqa.agent.browser import MaskRegion, SafeEvidenceService
from agentqa.contracts.observation import Modality
from agentqa.platform.security.egress import AllowedEndpoint
from agentqa.platform.security.redaction import RedactionService
from agentqa.platform.security.taint import TaintRegistry
from tests.support.browser import RecordingSink, run_async, start_stack
from tests.support.taskboard import TaskboardServer

CANARY = "canary-secret-77"


def build_service() -> tuple[SafeEvidenceService, RecordingSink, TaintRegistry]:
    taint = TaintRegistry()
    sink = RecordingSink()
    service = SafeEvidenceService(redactor=RedactionService(taint), sink=sink, taint=taint)
    return service, sink, taint


def render_canary_image(secret: str) -> bytes:
    image = Image.new("RGB", (320, 120), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.text((10, 20), f"token: {secret}", fill=(0, 0, 0))
    draw.text((10, 90), "NỘI DUNG TĨNH", fill=(20, 20, 20))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_semantic_and_network_sanitization() -> None:
    service, sink, taint = build_service()
    taint.register(CANARY)
    snapshot = {
        "aria": f"user {CANARY} logged in",
        "candidates": [{"id": "c0", "role": "textbox", "name": CANARY, "input_type": "password"}],
        "url": f"http://127.0.0.1/login?token={CANARY}&page=1",
    }
    sanitized = service.sanitize_semantic(snapshot)
    assert CANARY not in json.dumps(sanitized, ensure_ascii=False)
    assert sanitized["candidates"][0]["name"] == "[REDACTED]"
    service.emit_semantic("observation-x", snapshot)
    assert sink.records[-1]["media_type"] == "application/json"
    assert all(CANARY.encode() not in payload for payload in sink.payloads())

    network = service.sanitize_network(
        [
            {
                "url": f"http://127.0.0.1/a?token={CANARY}&page=2",
                "headers": {"Authorization": f"Bearer {CANARY}", "Accept": "text/html"},
            }
        ]
    )
    assert CANARY not in network[0]["url"]
    assert network[0]["headers"]["Authorization"] == "[REDACTED]"
    assert network[0]["headers"]["Accept"] == "text/html"
    assert "page=2" in network[0]["url"]

    redacted_url = service.sanitize_url(f"http://user:{CANARY}@127.0.0.1/api?q={CANARY}")
    assert CANARY not in redacted_url
    assert "REDACTED" in redacted_url

    with pytest.raises(ValueError):
        service.assert_sink_clean({"leak": CANARY})


def test_image_mask_canary_pixel_check() -> None:
    service, _sink, taint = build_service()
    taint.register(CANARY)
    original_a = render_canary_image("SECRET-A")
    original_b = render_canary_image("SECRET-B")
    assert original_a != original_b

    region = MaskRegion(x=0, y=0, width=320, height=60)
    masked_a = service.mask_image(original_a, [region])
    masked_b = service.mask_image(original_b, [region])
    pixels_a = Image.open(io.BytesIO(masked_a)).convert("RGB")
    pixels_b = Image.open(io.BytesIO(masked_b)).convert("RGB")
    assert pixels_a.tobytes() == pixels_b.tobytes()
    assert pixels_a.getpixel((5, 5)) == (0, 0, 0)
    assert pixels_a.getpixel((100, 30)) == (0, 0, 0)
    footer = [pixels_a.getpixel((x, y)) for x in range(10, 310, 10) for y in range(80, 118, 4)]
    assert any(pixel != (255, 255, 255) for pixel in footer)
    assert original_a != masked_a


def test_capture_safe_evidence_and_observe_with_real_browser(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    parts = urlsplit(taskboard_server.base_url)
    endpoint = AllowedEndpoint(host="127.0.0.1", port=parts.port or 80, addresses=("127.0.0.1",))

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[endpoint])
        try:
            assert stack.session.launch.native_trace is False
            await stack.session.contexts.open("capture-1")
            page = await stack.session.contexts.page("capture-1")
            await page.goto(f"{taskboard_server.base_url}/capture-1/login")
            observation = await stack.read_port.observe("capture-1", Modality.SEMANTIC)
            assert observation.mode == Modality.SEMANTIC
            assert observation.version == 2
            assert observation.semantic_ref is not None
            assert observation.candidate_refs
            semantic_payload = json.loads(stack.sink.payloads()[-1].decode("utf-8"))
            assert "candidates" in semantic_payload
            assert "aria" in semantic_payload
            ref = await stack.read_port.capture_safe_evidence("capture-1", "shot")
            assert ref.startswith("mem://")
            record = stack.sink.records[-1]
            assert record["media_type"] == "image/png"
            with Image.open(io.BytesIO(record["payload"])) as image:
                assert image.size[0] > 0
                assert image.size[1] > 0
        finally:
            await stack.aclose()

    run_async(scenario())
