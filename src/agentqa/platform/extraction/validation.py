from __future__ import annotations

import io
import zipfile
from pathlib import Path

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_RATIO = 200
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MEDIA_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
PDF_MEDIA_TYPE = "application/pdf"
REJECTED_REASONS = {
    "empty_file": "File rỗng",
    "size_exceeded": "File vượt quá giới hạn dung lượng",
    "unsupported_extension": "Định dạng file không được hỗ trợ",
    "mime_mismatch": "Nội dung file không khớp định dạng khai báo",
    "invalid_docx": "File DOCX không hợp lệ",
    "invalid_pdf": "File PDF không hợp lệ",
    "encrypted_file": "File được mã hoá, không thể trích xuất",
    "macro_content": "File chứa macro hoặc nội dung nhúng không được phép",
    "external_entity": "File chứa external entity không được phép",
    "path_traversal": "File chứa đường dẫn không an toàn",
    "decompression_bomb": "File nén vượt ngưỡng giải nén an toàn",
    "invalid_text_encoding": "File văn bản không đọc được theo UTF-8",
}


class UploadRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.message = REJECTED_REASONS.get(reason, "File upload bị từ chối")
        super().__init__(self.message)


def detect_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in (".md", ".markdown", ".txt"):
        return "text"
    raise UploadRejected("unsupported_extension")


def validate_upload(*, filename: str, payload: bytes) -> str:
    kind = detect_kind(filename)
    if not payload:
        raise UploadRejected("empty_file")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise UploadRejected("size_exceeded")
    if kind == "pdf":
        if not payload.startswith(b"%PDF-"):
            raise UploadRejected("mime_mismatch")
        return kind
    if kind == "docx":
        if not payload.startswith(b"PK\x03\x04"):
            raise UploadRejected("mime_mismatch")
        _validate_docx_container(payload)
        return kind
    if b"\x00" in payload[:4096]:
        raise UploadRejected("mime_mismatch")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UploadRejected("invalid_text_encoding") from error
    return kind


def _validate_docx_container(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                name = info.filename
                parts = name.replace("\\", "/").split("/")
                if name.startswith("/") or ".." in parts:
                    raise UploadRejected("path_traversal")
                if info.flag_bits & 0x1:
                    raise UploadRejected("encrypted_file")
                lowered = name.lower()
                if "vbaproject" in lowered or "embeddings/" in lowered:
                    raise UploadRejected("macro_content")
                total_uncompressed += info.file_size
                total_compressed += info.compress_size
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise UploadRejected("decompression_bomb")
            ratio = total_uncompressed / max(total_compressed, 1)
            if ratio > MAX_ZIP_RATIO:
                raise UploadRejected("decompression_bomb")
            if "word/document.xml" not in archive.namelist():
                raise UploadRejected("invalid_docx")
            for info in infos:
                lowered = info.filename.lower()
                if lowered.endswith(".xml") or lowered.endswith(".rels"):
                    if info.file_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                        raise UploadRejected("decompression_bomb")
                    head = archive.read(info).decode("utf-8", errors="replace")
                    if "<!DOCTYPE" in head or "<!ENTITY" in head:
                        raise UploadRejected("external_entity")
    except zipfile.BadZipFile as error:
        raise UploadRejected("invalid_docx") from error
    except RuntimeError as error:
        raise UploadRejected("encrypted_file") from error
