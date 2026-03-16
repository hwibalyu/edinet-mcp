from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


_CODELIST_URLS = {
    ("edinet", "ja"): "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip",
    ("edinet", "en"): "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelisteng/Edinetcode.zip",
    ("fund", "ja"): "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Fundcode.zip",
    ("fund", "en"): "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelisteng/Fundcode.zip",
}


class CodeListClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def _cache_zip_path(self, kind: str, lang: str) -> Path:
        return self.settings.cache_dir / f"{kind}_{lang}_codes.zip"

    def fetch_zip(self, kind: str = "edinet", lang: str = "ja", force_refresh: bool = False) -> Path:
        kind = kind.lower().strip()
        lang = lang.lower().strip()
        url = _CODELIST_URLS.get((kind, lang))
        if not url:
            raise ValueError("kind/lang must be one of: (edinet|fund) x (ja|en)")

        out = self._cache_zip_path(kind, lang)
        if out.exists() and not force_refresh:
            return out

        resp = self._http.get(url)
        resp.raise_for_status()
        out.write_bytes(resp.content)
        return out

    @staticmethod
    def _decode_csv(raw: bytes) -> str:
        for enc in ("utf-8-sig", "cp932", "shift_jis", "euc_jp"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def load_rows(self, kind: str = "edinet", lang: str = "ja", force_refresh: bool = False) -> dict[str, Any]:
        zip_path = self.fetch_zip(kind=kind, lang=lang, force_refresh=force_refresh)

        with zipfile.ZipFile(zip_path) as zf:
            csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_members:
                raise RuntimeError("No CSV found in code list ZIP")

            name = sorted(csv_members)[0]
            raw = zf.read(name)

        text = self._decode_csv(raw)
        buf = io.StringIO(text)
        reader = csv.DictReader(buf)

        rows: list[dict[str, str]] = []
        for row in reader:
            normalized: dict[str, str] = {}
            for k, v in row.items():
                key = str(k or "").strip().lstrip("\ufeff")
                if isinstance(v, list):
                    val = " ".join(str(x) for x in v if x is not None).strip()
                else:
                    val = str(v or "").strip()
                normalized[key] = val
            rows.append(normalized)

        return {
            "kind": kind,
            "lang": lang,
            "csv_file": name,
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "cache_zip": str(zip_path),
        }

    def search_rows(
        self,
        keyword: str,
        kind: str = "edinet",
        lang: str = "ja",
        *,
        field: str = "",
        limit: int = 20,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        payload = self.load_rows(kind=kind, lang=lang, force_refresh=force_refresh)
        rows = payload["rows"]

        keyword_lc = keyword.lower().strip()
        if not keyword_lc:
            raise ValueError("keyword is required")

        results = []
        for row in rows:
            if field:
                value = str(row.get(field, ""))
                if keyword_lc in value.lower():
                    results.append(row)
            else:
                haystack = " ".join(str(v) for v in row.values())
                if keyword_lc in haystack.lower():
                    results.append(row)

            if len(results) >= limit:
                break

        return {
            "kind": payload["kind"],
            "lang": payload["lang"],
            "csv_file": payload["csv_file"],
            "columns": payload["columns"],
            "match_count": len(results),
            "results": results,
        }
