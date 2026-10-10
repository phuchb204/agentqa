from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Frame, Page

PROVIDER_ENV_VARS = ("AGENTQA_JEV_API_KEY", "AGENTQA_LLM_API_KEY", "AGENTQA_TASKBOARD_CONTROL_TOKEN")


class SandboxUnsupported(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("sandbox profile không enforce được: " + "; ".join(reasons))


class ContextNotFound(KeyError):
    pass


class PageBindingError(RuntimeError):
    pass


class FrameNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserLaunchConfig:
    headless: bool = True
    args: tuple[str, ...] = ()
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    env_scrub: tuple[str, ...] = PROVIDER_ENV_VARS
    user_data_dir: str | None = None
    download_dir: str | None = None
    proxy_url: str | None = None
    workspace_root: str | None = None
    temp_root: str | None = None
    native_trace: bool = False

    def enforce(self) -> None:
        problems: list[str] = []
        if not self.proxy_url:
            problems.append("proxy_url bắt buộc cho outbound profile")
        if not self.user_data_dir:
            problems.append("user_data_dir bắt buộc")
        if not self.download_dir:
            problems.append("download_dir bắt buộc")
        if not self.env_scrub:
            problems.append("env_scrub bắt buộc")
        missing_provider_scrub = [name for name in PROVIDER_ENV_VARS if name not in self.env_scrub]
        if missing_provider_scrub:
            problems.append(f"env_scrub thiếu provider/control names: {missing_provider_scrub}")
        if self.native_trace:
            problems.append("native sensitive trace phải disabled ở gate này")
        workspace = Path(self.workspace_root).resolve() if self.workspace_root else None
        temp = Path(self.temp_root).resolve() if self.temp_root else None
        for label, value in (("user_data_dir", self.user_data_dir), ("download_dir", self.download_dir)):
            if not value:
                continue
            resolved = Path(value).resolve()
            if workspace is not None and is_within(resolved, workspace):
                problems.append(f"{label} nằm trong workspace: {resolved}")
            if temp is not None and not is_within(resolved, temp):
                problems.append(f"{label} phải nằm trong temp root: {resolved}")
        if problems:
            raise SandboxUnsupported(problems)

    def clean_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        source = os.environ if base is None else base
        scrubbed = {name for name in self.env_scrub}
        environment = {
            name: value
            for name, value in source.items()
            if name not in scrubbed and not (name.startswith("AGENTQA_") and name.endswith("_API_KEY"))
        }
        environment.update(self.env_overrides)
        return environment


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return None
    port = parts.port
    default = {"http": 80, "https": 443}.get(parts.scheme.lower())
    if port is None or port == default:
        return f"{parts.scheme.lower()}://{parts.hostname.lower()}"
    return f"{parts.scheme.lower()}://{parts.hostname.lower()}:{port}"


@dataclass(frozen=True)
class DialogPolicy:
    action: str
    expected_prompt: str | None = None
    prompt_text: str | None = None


@dataclass
class BrowserLane:
    context_key: str
    context: BrowserContext
    allowed_origins: tuple[str, ...]
    observation_version: int = 1
    pages: dict[str, Page] = field(default_factory=dict)
    active_frame_key: str | None = None
    dialog_policy: DialogPolicy | None = None
    unhandled_dialogs: list[str] = field(default_factory=list)

    def next_observation_version(self) -> int:
        self.observation_version += 1
        return self.observation_version


class ContextRegistry:
    def __init__(self, browser: Browser, launch: BrowserLaunchConfig) -> None:
        self._browser = browser
        self._launch = launch
        self._lanes: dict[str, BrowserLane] = {}
        self._wired_dialog_pages: set[int] = set()
        self._dialog_tasks: set[object] = set()

    def lane(self, context_key: str) -> BrowserLane:
        lane = self._lanes.get(context_key)
        if lane is None:
            raise ContextNotFound(context_key)
        return lane

    def context_keys(self) -> tuple[str, ...]:
        return tuple(self._lanes)

    async def open(
        self,
        context_key: str,
        *,
        allowed_origins: tuple[str, ...] = (),
        viewport: dict[str, int] | None = None,
    ) -> BrowserLane:
        if context_key in self._lanes:
            raise PageBindingError(f"context '{context_key}' đã tồn tại")
        context = await self._browser.new_context(
            viewport=viewport or {"width": 1280, "height": 800},
            accept_downloads=True,
        )
        lane = BrowserLane(context_key=context_key, context=context, allowed_origins=allowed_origins)
        self._lanes[context_key] = lane
        return lane

    async def page(self, context_key: str, page_key: str = "main") -> Page:
        lane = self.lane(context_key)
        existing = lane.pages.get(page_key)
        if existing is not None:
            return existing
        page = lane.context.pages[0] if lane.context.pages else await lane.context.new_page()
        lane.pages[page_key] = page
        self._wire_dialogs(lane, page)
        return page

    def _wire_dialogs(self, lane: BrowserLane, page: Page) -> None:
        if id(page) in self._wired_dialog_pages:
            return
        self._wired_dialog_pages.add(id(page))

        async def handle(dialog) -> None:
            policy = lane.dialog_policy
            if policy is None:
                lane.unhandled_dialogs.append((dialog.message or "")[:120])
                await dialog.dismiss()
                return
            if policy.expected_prompt is not None and policy.expected_prompt not in (dialog.message or ""):
                lane.unhandled_dialogs.append((dialog.message or "")[:120])
                lane.dialog_policy = None
                await dialog.dismiss()
                return
            lane.dialog_policy = None
            if policy.action == "accept":
                await dialog.accept(policy.prompt_text)
            else:
                await dialog.dismiss()

        def on_dialog(dialog) -> None:
            import asyncio

            task = asyncio.ensure_future(handle(dialog))
            self._dialog_tasks.add(task)
            task.add_done_callback(self._dialog_tasks.discard)

        page.on("dialog", on_dialog)

    async def locator_root(self, context_key: str, page_key: str = "main") -> Page | Frame:
        lane = self.lane(context_key)
        page = await self.page(context_key, page_key)
        if lane.active_frame_key is None:
            return page
        return await self.frame(context_key, page_key, lane.active_frame_key)

    async def bind_page(
        self,
        context_key: str,
        page_key: str,
        page: Page,
        *,
        allowed_origins: tuple[str, ...] | None = None,
    ) -> Page:
        lane = self.lane(context_key)
        origins = allowed_origins if allowed_origins is not None else lane.allowed_origins
        current = page.url
        if current and current != "about:blank" and origins:
            origin = origin_of(current)
            if origin not in origins:
                raise PageBindingError(f"origin '{origin}' không khớp expectation cho tab mới")
        lane.pages[page_key] = page
        return page

    async def frame(self, context_key: str, page_key: str, frame_key: str) -> Frame:
        page = await self.page(context_key, page_key)
        for frame in page.frames:
            if frame.name == frame_key or (frame.url and frame.url.endswith(frame_key)):
                return frame
        raise FrameNotFound(frame_key)

    async def frame_names(self, context_key: str, page_key: str) -> list[str]:
        page = await self.page(context_key, page_key)
        return [frame.name or frame.url for frame in page.frames]

    async def close(self, context_key: str) -> None:
        lane = self._lanes.pop(context_key, None)
        if lane is not None:
            await lane.context.close()

    async def close_all(self) -> None:
        for lane in list(self._lanes.values()):
            await lane.context.close()
        self._lanes.clear()
