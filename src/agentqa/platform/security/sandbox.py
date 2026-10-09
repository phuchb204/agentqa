from __future__ import annotations

import sys
from dataclasses import dataclass

from agentqa.agent.browser.contexts import BrowserLaunchConfig


@dataclass(frozen=True)
class SandboxProfile:
    name: str
    platform: str
    launch: BrowserLaunchConfig

    def enforce(self) -> None:
        self.launch.enforce()


def select_profile(workspace_root: str, temp_root: str, proxy_url: str) -> SandboxProfile:
    if sys.platform == "win32":
        from agentqa.platform.security.sandbox_windows import windows_profile

        return windows_profile(workspace_root=workspace_root, temp_root=temp_root, proxy_url=proxy_url)
    from agentqa.platform.security.sandbox_linux import linux_profile

    return linux_profile(workspace_root=workspace_root, temp_root=temp_root, proxy_url=proxy_url)
