from __future__ import annotations

from pathlib import Path

from agentqa.agent.browser.contexts import PROVIDER_ENV_VARS, BrowserLaunchConfig
from agentqa.platform.security.sandbox import SandboxProfile

WINDOWS_ARGS = (
    "--disable-background-networking",
    "--disable-sync",
    "--disable-component-update",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,OptimizationHints",
)


def windows_profile(
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
        args=WINDOWS_ARGS,
        env_overrides={
            "USERPROFILE": str(temp / "user"),
            "LOCALAPPDATA": str(temp / "localappdata"),
            "TEMP": str(temp),
            "TMP": str(temp),
        },
        env_scrub=PROVIDER_ENV_VARS,
        user_data_dir=user_data_dir or str(temp / "browser-profile"),
        download_dir=download_dir or str(temp / "downloads"),
        proxy_url=proxy_url,
        workspace_root=str(code),
        temp_root=str(temp),
        native_trace=False,
    )
    profile = SandboxProfile(name="windows-browser", platform="win32", launch=launch)
    profile.enforce()
    return profile
