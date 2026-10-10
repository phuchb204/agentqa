from __future__ import annotations

import os
import sys
from pathlib import Path

from agentqa.platform.api.application import create_application
from agentqa.platform.api.runtime import PlatformRuntime, RuntimeProfile
from agentqa.platform.artifacts.store import FileSystemBlobStore
from agentqa.platform.storage.roles import ROLE_API, ROLE_WORKER

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_ARTIFACT_DIR = "/var/lib/agentqa/artifacts"


def build_runtime_from_env() -> PlatformRuntime:
    dsn = os.environ.get("AGENTQA_DSN")
    if not dsn:
        raise SystemExit("Thiếu biến môi trường AGENTQA_DSN")
    dsn_by_role = {ROLE_API: dsn}
    worker_dsn = os.environ.get("AGENTQA_WORKER_DSN")
    if worker_dsn:
        dsn_by_role[ROLE_WORKER] = worker_dsn
    shared_origins = [item.strip() for item in os.environ.get("AGENTQA_SHARED_ORIGINS", "").split(",") if item.strip()]
    profile = RuntimeProfile.shared(frozenset(shared_origins)) if shared_origins else RuntimeProfile.local()
    artifact_dir = Path(os.environ.get("AGENTQA_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR))
    return PlatformRuntime.build(
        profile=profile,
        dsn_by_role=dsn_by_role,
        artifact_store=FileSystemBlobStore(artifact_dir),
    )


def main(argv: list[str] | None = None) -> int:
    _ = argv
    import uvicorn

    from agentqa.platform.storage.database import configure_event_loop_policy
    from agentqa.platform.telemetry import configure_logging

    configure_event_loop_policy()
    configure_logging(os.environ.get("AGENTQA_LOG_LEVEL", "INFO"))
    runtime = build_runtime_from_env()
    app = create_application(runtime)
    uvicorn.run(
        app,
        host=os.environ.get("AGENTQA_API_HOST", DEFAULT_HOST),
        port=int(os.environ.get("AGENTQA_API_PORT", DEFAULT_PORT)),
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
