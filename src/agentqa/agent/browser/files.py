from __future__ import annotations

import re
from pathlib import Path

FILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class FileIdRejected(ValueError):
    pass


class DirectoryFileResolver:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def resolve(self, file_id: str) -> Path:
        if not FILE_ID_PATTERN.match(file_id):
            raise FileIdRejected(f"file id không hợp lệ: {file_id!r}")
        candidate = (self._root / file_id).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as error:
            raise FileIdRejected("file id thoát khỏi catalog") from error
        return candidate
