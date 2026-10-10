from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from agentqa.contracts.case import SourceAnchor
from agentqa.contracts.values import StrictModel

NETWORK_BLOCK_PREAMBLE = """
import socket

def _blocked(*args, **kwargs):
    raise OSError("network blocked in extraction sandbox")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
"""

BOOTSTRAP = (
    NETWORK_BLOCK_PREAMBLE
    + """
from agentqa.platform.extraction.runner import main

raise SystemExit(main())
"""
)

ENV_ALLOWLIST = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATHEXT")


class ExtractionError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RunnerSegment(StrictModel):
    anchor: SourceAnchor
    text: str


class RunnerResult(StrictModel):
    status: Literal["extracted", "unextractable", "rejected"]
    reason: str | None = None
    segments: list[RunnerSegment] = Field(default_factory=list)


def _sandbox_environment() -> dict[str, str]:
    environment = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for name in ENV_ALLOWLIST:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


class ExtractionService:
    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self._timeout = timeout_seconds

    def run(self, *, kind: str, payload: bytes) -> RunnerResult:
        with tempfile.TemporaryDirectory(prefix="agentqa-extract-") as raw:
            workdir = Path(raw)
            input_path = workdir / "input.bin"
            spec_path = workdir / "spec.json"
            output_path = workdir / "result.json"
            input_path.write_bytes(payload)
            spec_path.write_text(json.dumps({"kind": kind, "input_path": str(input_path)}), encoding="utf-8")
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-c", BOOTSTRAP, str(spec_path), str(output_path)],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=workdir,
                    env=_sandbox_environment(),
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ExtractionError("extraction_timeout") from error
            if completed.returncode != 0 or not output_path.is_file():
                raise ExtractionError("extraction_failed")
            try:
                return RunnerResult.model_validate_json(output_path.read_text(encoding="utf-8"))
            except ValueError as error:
                raise ExtractionError("extraction_result_invalid") from error
