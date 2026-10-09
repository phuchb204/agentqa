from __future__ import annotations

from playwright.async_api import Playwright, async_playwright

from agentqa.agent.browser.contexts import BrowserLaunchConfig, ContextRegistry


class BrowserSession:
    def __init__(self, launch: BrowserLaunchConfig) -> None:
        self.launch = launch
        self._playwright: Playwright | None = None
        self._browser = None
        self._registry: ContextRegistry | None = None
        self.launch_env: dict[str, str] | None = None

    async def start(self) -> None:
        self.launch.enforce()
        environment = self.launch.clean_environment()
        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, object] = {
            "headless": self.launch.headless,
            "args": list(self.launch.args),
            "env": environment,
        }
        if self.launch.proxy_url:
            launch_kwargs["proxy"] = {"server": self.launch.proxy_url}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self.launch_env = environment
        self._registry = ContextRegistry(self._browser, self.launch)

    @property
    def contexts(self) -> ContextRegistry:
        if self._registry is None:
            raise RuntimeError("BrowserSession chưa start")
        return self._registry

    @property
    def is_started(self) -> bool:
        return self._browser is not None

    async def close(self) -> None:
        if self._registry is not None:
            await self._registry.close_all()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._registry = None
