from __future__ import annotations

import os
from pathlib import Path


class BlobStoreError(Exception):
    pass


def validate_object_key(key: str) -> tuple[str, ...]:
    if not key or key.startswith("/") or "\\" in key:
        raise BlobStoreError("object key không hợp lệ")
    parts = tuple(part for part in key.split("/") if part)
    if not parts:
        raise BlobStoreError("object key rỗng")
    for part in parts:
        if part in (".", ".."):
            raise BlobStoreError("object key chứa traversal")
    return parts


class FileSystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        parts = validate_object_key(key)
        current = self._root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise BlobStoreError("symlink bị từ chối trong blob store")
        resolved = current.resolve()
        if not str(resolved).startswith(str(self._root.resolve())):
            raise BlobStoreError("object key thoát khỏi blob root")
        return resolved

    def write(self, key: str, payload: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)

    def read(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise BlobStoreError("blob không tồn tại")
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except BlobStoreError:
            return False

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            target.unlink()


class FaultBlobStore(FileSystemBlobStore):
    def __init__(self, root: Path, *, fail_on_write: bool = False, fail_on_read: bool = False) -> None:
        super().__init__(root)
        self.fail_on_write = fail_on_write
        self.fail_on_read = fail_on_read

    def write(self, key: str, payload: bytes) -> None:
        if self.fail_on_write:
            raise BlobStoreError("fault-injected write failure")
        super().write(key, payload)

    def read(self, key: str) -> bytes:
        if self.fail_on_read:
            raise BlobStoreError("fault-injected read failure")
        return super().read(key)
