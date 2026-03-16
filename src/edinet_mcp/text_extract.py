from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser

from pypdf import PdfReader


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        data = data.strip()
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(self.parts)



def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc_jp", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")



def extract_text_from_pdf_bytes(blob: bytes, max_chars: int = 20000) -> str:
    reader = PdfReader(io.BytesIO(blob))
    chunks: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            chunks.append(f"\n[PAGE {idx}]\n{page_text.strip()}")
        joined = "\n".join(chunks)
        if len(joined) >= max_chars:
            return joined[:max_chars]
    return "\n".join(chunks)[:max_chars]



def extract_text_from_zip_bytes(blob: bytes, max_chars: int = 30000) -> dict[str, object]:
    candidates = (".xbrl", ".xml", ".xsd", ".htm", ".html", ".txt", ".csv")

    output_parts: list[str] = []
    parsed_files: list[str] = []

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = sorted(zf.namelist())
        for name in names:
            lower = name.lower()
            if not lower.endswith(candidates):
                continue

            raw = zf.read(name)
            text = _decode_bytes(raw)

            if lower.endswith((".htm", ".html", ".xml", ".xbrl", ".xsd")):
                parser = _HTMLTextExtractor()
                parser.feed(text)
                parsed = parser.text()
                if not parsed.strip():
                    parsed = re.sub(r"<[^>]+>", " ", text)
            else:
                parsed = text

            parsed = re.sub(r"\s+", " ", parsed).strip()
            if not parsed:
                continue

            parsed_files.append(name)
            output_parts.append(f"\n[FILE {name}]\n{parsed}")

            joined = "\n".join(output_parts)
            if len(joined) >= max_chars:
                return {
                    "text": joined[:max_chars],
                    "parsed_files": parsed_files,
                    "truncated": True,
                }

    joined = "\n".join(output_parts)
    return {
        "text": joined[:max_chars],
        "parsed_files": parsed_files,
        "truncated": len(joined) > max_chars,
    }
