from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for extra_path in ("benchmarks/apps/canvasdesk", "benchmarks/apps/shopflow", "benchmarks/apps/taskboard"):
    candidate = str(REPO_ROOT / extra_path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

VISUAL_DIR = Path(__file__).resolve().parent / "visual"
INDEX_PATH = Path(__file__).resolve().parent / "index.yaml"
VIEWPORT = {"width": 1280, "height": 800}
USERNAME = "alice"


def canvasdesk_password(namespace: str, username: str) -> str:
    material = f"canvasdesk-synthetic:{namespace}:{username}".encode()
    return "cd-" + hashlib.sha256(material).hexdigest()[:20]


async def capture(namespace: str, base_url: str, control_token: str) -> dict[str, bytes]:
    import httpx
    import uvicorn
    from canvasdesk import create_canvasdesk_app
    from playwright.async_api import async_playwright

    from agentqa.platform.fixtures import CANVASDESK_FIXTURE

    app = create_canvasdesk_app(control_token)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("canvasdesk không khởi động")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    shots: dict[str, bytes] = {}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{base_url}/_control/namespaces/{namespace}/prepare",
                json={
                    "accounts": {USERNAME: canvasdesk_password(namespace, USERNAME)},
                    "cells": CANVASDESK_FIXTURE.seeds["default"]["cells"],
                },
                headers={"x-canvasdesk-control": control_token},
            )
            response.raise_for_status()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            context = await browser.new_context(viewport=VIEWPORT)
            page = await context.new_page()
            await page.goto(f"{base_url}/{namespace}/login")
            await page.get_by_label("Tài khoản").fill(USERNAME)
            await page.get_by_label("Mật khẩu").fill(canvasdesk_password(namespace, USERNAME))
            await page.get_by_role("button", name="Đăng nhập").click()
            await page.wait_for_url(f"**/{namespace}/board")
            await page.wait_for_timeout(300)
            box = await page.locator("#board-canvas").bounding_box()
            if not box or box["y"] < 40 or box["y"] + box["height"] > 252:
                raise RuntimeError(f"canvas ngoài vùng so khớp: {box}")
            shots["canvasdesk_default_light"] = await page.screenshot(type="png")
            await page.get_by_role("button", name="Đổi nền").click()
            await page.wait_for_url(f"**/{namespace}/board")
            await page.wait_for_timeout(300)
            shots["canvasdesk_default_dark"] = await page.screenshot(type="png")
            await context.close()
            await browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    return shots


def update_index(names: list[str]) -> None:
    import yaml

    index = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    visual_entries = {entry["ref"]: entry for entry in index.get("visual_baselines", [])}
    for name in names:
        path = VISUAL_DIR / f"{name}.png"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        visual_entries[name] = {"ref": name, "path": f"benchmarks/public/baselines/visual/{name}.png", "sha256": digest}
    index["visual_baselines"] = [visual_entries[name] for name in sorted(visual_entries)]
    INDEX_PATH.write_text(yaml.safe_dump(index, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_visual", description="Author visual baselines cho canvasdesk")
    parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    VISUAL_DIR.mkdir(parents=True, exist_ok=True)
    control_token = secrets.token_urlsafe(16)
    shots = asyncio.run(capture("profile-visual-authoring", "", control_token))
    for name, data in shots.items():
        (VISUAL_DIR / f"{name}.png").write_bytes(data)
        print(f"[WROTE] visual/{name}.png ({len(data)} bytes)")
    update_index(list(shots))
    print(json.dumps({"captured": sorted(shots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
