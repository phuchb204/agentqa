from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from agentqa.agent.browser import (
    BrowserLaunchConfig,
    BrowserSession,
    ContextNotFound,
    FrameNotFound,
    PageBindingError,
    SandboxUnsupported,
)
from agentqa.platform.security.egress import AllowedEndpoint
from agentqa.platform.security.sandbox import select_profile
from tests.support.browser import REPO_ROOT, TrapServer, run_async, start_stack
from tests.support.taskboard import TaskboardServer


def taskboard_endpoint(server: TaskboardServer) -> AllowedEndpoint:
    parts = urlsplit(server.base_url)
    return AllowedEndpoint(host="127.0.0.1", port=parts.port or 80, addresses=("127.0.0.1",))


def test_context_lifecycle_private_channel_and_env_scrub(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open("run-1", allowed_origins=("http://127.0.0.1",))
            page = await stack.session.contexts.page("run-1")
            await page.goto(f"{taskboard_server.base_url}/demo/login")
            assert "Đăng nhập" in await page.title()
            assert stack.session.is_started
            assert not hasattr(stack.session, "cdp_url")
            public_read_names = [name for name in dir(stack.read_port) if not name.startswith("_")]
            assert "cdp" not in " ".join(public_read_names).lower()
            assert "evaluate" not in public_read_names
            assert stack.session.launch_env is not None
            assert "AGENTQA_LLM_API_KEY" not in stack.session.launch_env
            assert "AGENTQA_JEV_API_KEY" not in stack.session.launch_env
            assert "AGENTQA_TASKBOARD_CONTROL_TOKEN" not in stack.session.launch_env
            with pytest.raises(ContextNotFound):
                stack.session.contexts.lane("khong-ton-tai")
            await stack.session.contexts.close("run-1")
            with pytest.raises(ContextNotFound):
                stack.session.contexts.lane("run-1")
        finally:
            await stack.aclose()

    run_async(scenario())


def test_frame_lookup_and_missing_frame(tmp_path: Path) -> None:
    trap = TrapServer()
    trap.route(
        "/frame-page",
        body='<html><body><iframe name="inner" src="/inside"></iframe></body></html>',
    )
    trap.route("/inside", body='<p id="inner-text">nội dung frame</p>')
    trap.start()

    async def scenario() -> None:
        stack = await start_stack(
            temp_root=tmp_path,
            endpoints=[AllowedEndpoint(host="127.0.0.1", port=trap.port, addresses=("127.0.0.1",))],
        )
        try:
            await stack.session.contexts.open("frame-run")
            page = await stack.session.contexts.page("frame-run")
            await page.goto(f"{trap.base_url}/frame-page")
            frame = await stack.session.contexts.frame("frame-run", "main", "inner")
            assert frame.name == "inner"
            text = await frame.locator("#inner-text").inner_text()
            assert text == "nội dung frame"
            names = await stack.session.contexts.frame_names("frame-run", "main")
            assert "inner" in names
            with pytest.raises(FrameNotFound):
                await stack.session.contexts.frame("frame-run", "main", "khong-co")
        finally:
            await stack.aclose()

    try:
        run_async(scenario())
    finally:
        trap.stop()


def test_new_tab_binding_checks_origin(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    allowed_origin = f"http://127.0.0.1:{urlsplit(taskboard_server.base_url).port}"

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            lane = await stack.session.contexts.open("tab-run", allowed_origins=(allowed_origin,))
            second = await lane.context.new_page()
            await second.goto(f"{taskboard_server.base_url}/demo/login")
            bound = await stack.session.contexts.bind_page("tab-run", "second", second)
            assert bound is second
            with pytest.raises(PageBindingError):
                await stack.session.contexts.bind_page(
                    "tab-run", "third", second, allowed_origins=("http://other-origin.test",)
                )
        finally:
            await stack.aclose()

    run_async(scenario())


def test_context_cookie_isolation(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            lane_one = await stack.session.contexts.open("iso-1")
            lane_two = await stack.session.contexts.open("iso-2")
            await lane_one.context.add_cookies(
                [{"name": "tb_session", "value": "synthetic", "url": taskboard_server.base_url}]
            )
            cookies_one = await lane_one.context.cookies()
            cookies_two = await lane_two.context.cookies()
            assert any(cookie["name"] == "tb_session" for cookie in cookies_one)
            assert cookies_two == []
        finally:
            await stack.aclose()

    run_async(scenario())


def test_sandbox_profile_enforcement_fails_startup(tmp_path: Path) -> None:
    def launch_config(proxy_url: str | None = "http://127.0.0.1:1", native_trace: bool = False) -> BrowserLaunchConfig:
        return BrowserLaunchConfig(
            proxy_url=proxy_url,
            user_data_dir=str(tmp_path / "profile"),
            download_dir=str(tmp_path / "downloads"),
            workspace_root=str(REPO_ROOT),
            temp_root=str(tmp_path),
            native_trace=native_trace,
        )

    with pytest.raises(SandboxUnsupported):
        launch_config(proxy_url=None).enforce()
    with pytest.raises(SandboxUnsupported):
        launch_config(native_trace=True).enforce()
    with pytest.raises(SandboxUnsupported):
        select_profile(
            workspace_root=str(REPO_ROOT),
            temp_root=str(REPO_ROOT / ".sandbox-inside-repo"),
            proxy_url="http://127.0.0.1:1",
        )
    launch_config().enforce()

    async def scenario() -> None:
        session = BrowserSession(launch_config(proxy_url=None))
        with pytest.raises(SandboxUnsupported):
            await session.start()

    run_async(scenario())
