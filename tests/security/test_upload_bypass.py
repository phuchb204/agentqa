from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentqa.agent.browser.files import DirectoryFileResolver, FileIdRejected

REJECTED_IDS = (
    "../secret.txt",
    "..\\secret.txt",
    "a/../../etc/passwd",
    "/etc/passwd",
    "",
    "sub dir/file.txt",
    ":stream.txt",
    "dir\\windows.txt",
)


def test_resolver_rejects_traversal_and_absolute_ids(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    resolver = DirectoryFileResolver(root)
    for file_id in REJECTED_IDS:
        with pytest.raises(FileIdRejected):
            resolver.resolve(file_id)


def test_resolver_accepts_catalog_ids_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "mau-don.txt").write_text("noi dung", encoding="utf-8")
    resolver = DirectoryFileResolver(root)
    resolved = resolver.resolve("mau-don.txt")
    assert resolved == (root / "mau-don.txt").resolve()
    assert resolver.resolve("khong-ton-tai.png").is_file() is False


def test_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("symlink test chỉ chạy trên nền tảng hỗ trợ")
    root = tmp_path / "catalog"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "bi-mat.txt").write_text("secret-outside", encoding="utf-8")
    link = root / "thoat.txt"
    try:
        link.symlink_to(outside / "bi-mat.txt")
    except OSError:
        pytest.skip("không tạo được symlink trong môi trường này")
    resolver = DirectoryFileResolver(root)
    with pytest.raises(FileIdRejected):
        resolver.resolve("thoat.txt")
