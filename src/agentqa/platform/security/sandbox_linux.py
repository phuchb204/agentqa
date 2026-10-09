from __future__ import annotations

from pathlib import Path

from agentqa.agent.browser.contexts import PROVIDER_ENV_VARS, BrowserLaunchConfig
from agentqa.platform.security.sandbox import SandboxProfile

LINUX_ARGS = (
    "--disable-background-networking",
    "--disable-sync",
    "--disable-component-update",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
)


def linux_profile(
    *,
    workspace_root: str,
    temp_root: str,
    proxy_url: str,
    user_data_dir: str | None = None,
    download_dir: str | None = None,
) -> SandboxProfile:
    temp = Path(temp_root)
    code = Path(workspace_root)
    launch = BrowserLaunchConfig(
        headless=True,
        args=LINUX_ARGS,
        env_overrides={
            "HOME": str(temp / "home"),
            "XDG_CONFIG_HOME": str(temp / "config"),
            "XDG_CACHE_HOME": str(temp / "cache"),
            "TMPDIR": str(temp),
        },
        env_scrub=PROVIDER_ENV_VARS,
        user_data_dir=user_data_dir or str(temp / "browser-profile"),
        download_dir=download_dir or str(temp / "downloads"),
        proxy_url=proxy_url,
        workspace_root=str(code),
        temp_root=str(temp),
        native_trace=False,
    )
    profile = SandboxProfile(name="linux-browser", platform="linux", launch=launch)
    profile.enforce()
    return profile
