from __future__ import annotations

import json
import sys
from pathlib import Path


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _pdf_segments(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        raise _Rejected("encrypted_file")
    segments: list[dict] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append({"anchor": {"type": "page", "value": number}, "text": text})
    return segments


def _docx_segments(path: Path) -> list[dict]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    segments: list[dict] = []
    paragraph_index = 0
    table_index = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            style_name = paragraph.style.name if paragraph.style is not None else ""
            if text:
                if style_name and style_name.lower().startswith("heading"):
                    segments.append({"anchor": {"type": "heading", "value": text}, "text": text})
                else:
                    segments.append({"anchor": {"type": "paragraph", "value": paragraph_index}, "text": text})
            paragraph_index += 1
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row_index, row in enumerate(table.rows):
                for column_index, cell in enumerate(row.cells):
                    text = cell.text.strip()
                    if text:
                        segments.append(
                            {
                                "anchor": {
                                    "type": "table_cell",
                                    "table_index": table_index,
                                    "row": row_index,
                                    "column": column_index,
                                },
                                "text": text,
                            }
                        )
            table_index += 1
    return segments


def _text_segments(path: Path) -> list[dict]:
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _Rejected("invalid_text_encoding") from error
    segments: list[dict] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            segments.append({"anchor": {"type": "section", "value": current_title or "body"}, "text": body})

    for line in text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                flush()
                current_title = heading
                current_lines = []
                continue
        current_lines.append(line)
    flush()
    return segments


def extract(spec: dict) -> dict:
    kind = spec.get("kind")
    path = Path(str(spec.get("input_path", "")))
    try:
        if kind == "pdf":
            segments = _pdf_segments(path)
        elif kind == "docx":
            segments = _docx_segments(path)
        elif kind == "text":
            segments = _text_segments(path)
        else:
            return {"status": "rejected", "reason": "unsupported_extension", "segments": []}
    except _Rejected as rejection:
        return {"status": "rejected", "reason": rejection.reason, "segments": []}
    except Exception:
        reason = "invalid_pdf" if kind == "pdf" else "invalid_docx"
        return {"status": "rejected", "reason": reason, "segments": []}
    if not segments:
        return {"status": "unextractable", "reason": "no_extractable_text", "segments": []}
    return {"status": "extracted", "reason": None, "segments": segments}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    spec_path = Path(args[0])
    output_path = Path(args[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    result = extract(spec)
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
