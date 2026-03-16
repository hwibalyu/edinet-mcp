from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class EdinetApiError(RuntimeError):
    def __init__(self, status: str | int, message: str):
        super().__init__(f"EDINET API error [{status}]: {message}")
        self.status = status
        self.message = message


@dataclass
class DownloadResult:
    doc_id: str
    doc_type: int
    content_type: str
    file_path: Path
    size_bytes: int


class EdinetClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def _url(self, path: str) -> str:
        return f"{self.settings.api_base_url}{path}"

    @staticmethod
    def _parse_status(payload: dict[str, Any]) -> tuple[str | int | None, str | None]:
        if "statusCode" in payload:
            return payload.get("statusCode"), payload.get("message")

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            return metadata.get("status"), metadata.get("message")
        return None, None

    @staticmethod
    def _ensure_success_payload(payload: dict[str, Any]) -> dict[str, Any]:
        status, message = EdinetClient._parse_status(payload)
        if status is None:
            return payload

        status_str = str(status)
        if status_str != "200":
            raise EdinetApiError(status=status_str, message=message or "Unknown API error")
        return payload

    @staticmethod
    def _validate_date(date: str) -> str:
        try:
            dt.datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date must be YYYY-MM-DD") from exc
        return date

    def list_documents(self, date: str, include_documents: bool = True) -> dict[str, Any]:
        self._validate_date(date)
        doc_type = "2" if include_documents else "1"
        params = {
            "date": date,
            "type": doc_type,
            "Subscription-Key": self.settings.api_key,
        }
        resp = self._http.get(self._url("/api/v2/documents.json"), params=params)
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise RuntimeError(f"Unexpected content-type for list API: {content_type}")

        payload = resp.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected JSON payload")
        return self._ensure_success_payload(payload)

    def get_document_binary(self, doc_id: str, doc_type: int) -> tuple[bytes, str]:
        if doc_type not in {1, 2, 3, 4, 5}:
            raise ValueError("doc_type must be one of 1,2,3,4,5")

        params = {
            "type": str(doc_type),
            "Subscription-Key": self.settings.api_key,
        }
        resp = self._http.get(self._url(f"/api/v2/documents/{doc_id}"), params=params)
        content_type = resp.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = resp.json()
            if isinstance(payload, dict):
                status, message = self._parse_status(payload)
                raise EdinetApiError(status or "unknown", message or "Document request failed")
            raise RuntimeError("Invalid JSON error payload from EDINET")

        if doc_type == 2 and "application/pdf" not in content_type:
            raise RuntimeError(f"Unexpected content-type for PDF download: {content_type}")

        if doc_type in {1, 3, 4, 5} and "application/octet-stream" not in content_type:
            raise RuntimeError(f"Unexpected content-type for ZIP download: {content_type}")

        return resp.content, content_type

    def download_document(
        self,
        doc_id: str,
        doc_type: int,
        save_dir: str | Path | None = None,
        overwrite: bool = False,
    ) -> DownloadResult:
        save_dir_path = Path(save_dir) if save_dir else self.settings.download_dir
        save_dir_path.mkdir(parents=True, exist_ok=True)

        extension = "pdf" if doc_type == 2 else "zip"
        out = save_dir_path / f"{doc_id}_type{doc_type}.{extension}"

        if out.exists() and not overwrite:
            return DownloadResult(
                doc_id=doc_id,
                doc_type=doc_type,
                content_type=("application/pdf" if doc_type == 2 else "application/octet-stream"),
                file_path=out,
                size_bytes=out.stat().st_size,
            )

        blob, content_type = self.get_document_binary(doc_id=doc_id, doc_type=doc_type)
        out.write_bytes(blob)

        return DownloadResult(
            doc_id=doc_id,
            doc_type=doc_type,
            content_type=content_type,
            file_path=out,
            size_bytes=len(blob),
        )

    def search_documents(
        self,
        from_date: str,
        to_date: str,
        *,
        query: str = "",
        edinet_code: str = "",
        sec_code: str = "",
        doc_type_code: str = "",
        ordinance_code: str = "",
        form_code: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        self._validate_date(from_date)
        self._validate_date(to_date)

        start = dt.datetime.strptime(from_date, "%Y-%m-%d").date()
        end = dt.datetime.strptime(to_date, "%Y-%m-%d").date()
        if end < start:
            raise ValueError("to_date must be >= from_date")

        total_days = (end - start).days + 1
        if total_days > 366:
            raise ValueError("Date range too large. Use 366 days or fewer per request.")

        query_lc = query.lower().strip()
        wanted_edinet = edinet_code.strip()
        wanted_sec = sec_code.strip()
        wanted_doc_type = doc_type_code.strip()
        wanted_ordinance = ordinance_code.strip()
        wanted_form = form_code.strip()

        rows: list[dict[str, Any]] = []
        scanned_dates = 0

        day = start
        while day <= end:
            scanned_dates += 1
            payload = self.list_documents(day.isoformat(), include_documents=True)
            results = payload.get("results") or []
            if isinstance(results, list):
                for row in results:
                    if isinstance(row, dict):
                        rows.append(row)
            day += dt.timedelta(days=1)

        # Infer issuer/subject scope from security code to support "issuer-centric" queries.
        related_edinet_codes: set[str] = set()
        if wanted_sec:
            for row in rows:
                row_sec = str(row.get("secCode", "") or "")
                row_edinet = str(row.get("edinetCode", "") or "").upper()
                if row_sec.startswith(wanted_sec) and row_edinet:
                    related_edinet_codes.add(row_edinet)

        matches: list[dict[str, Any]] = []
        for row in rows:
            row_edinet = str(row.get("edinetCode", "") or "").upper()
            row_issuer = str(row.get("issuerEdinetCode", "") or "").upper()
            row_subject = str(row.get("subjectEdinetCode", "") or "").upper()
            row_sec = str(row.get("secCode", "") or "")

            if wanted_edinet and not (
                row_edinet == wanted_edinet.upper()
                or row_issuer == wanted_edinet.upper()
                or row_subject == wanted_edinet.upper()
            ):
                continue
            if wanted_sec and not (
                row_sec.startswith(wanted_sec)
                or row_edinet in related_edinet_codes
                or row_issuer in related_edinet_codes
                or row_subject in related_edinet_codes
            ):
                continue
            if wanted_doc_type and str(row.get("docTypeCode", "")) != wanted_doc_type:
                continue
            if wanted_ordinance and str(row.get("ordinanceCode", "")) != wanted_ordinance:
                continue
            if wanted_form and str(row.get("formCode", "")) != wanted_form:
                continue

            if query_lc:
                haystack = " ".join(
                    [
                        str(row.get("filerName", "")),
                        str(row.get("docDescription", "")),
                        str(row.get("docID", "")),
                    ]
                ).lower()
                if query_lc not in haystack:
                    continue
            matches.append(row)

        matches = sorted(matches, key=lambda r: str(r.get("submitDateTime", "")), reverse=True)

        truncated = len(matches) > limit
        matches = matches[:limit]

        return {
            "from_date": from_date,
            "to_date": to_date,
            "scanned_dates": scanned_dates,
            "count": len(matches),
            "truncated": truncated,
            "results": matches,
        }
