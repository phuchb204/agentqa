from __future__ import annotations

import os
from pathlib import Path

from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except Exception:
            index = Path(self.directory) / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise


def web_dist_directory() -> Path | None:
    raw = os.environ.get("AGENTQA_WEB_DIST", "")
    if not raw:
        return None
    directory = Path(raw)
    if (directory / "index.html").is_file():
        return directory
    return None
