from __future__ import annotations

import datetime as dt
import re
from typing import Any

from fastmcp import FastMCP

from edinet_mcp.client import EdinetApiError, EdinetClient
from edinet_mcp.codelist import CodeListClient
from edinet_mcp.config import get_settings
from edinet_mcp.text_extract import extract_text_from_pdf_bytes, extract_text_from_zip_bytes


settings = get_settings()
edinet = EdinetClient(settings)
codelist = CodeListClient(settings)

mcp = FastMCP(
    name="edinet-mcp",
    instructions=(
        "EDINET MCP server for filings discovery, retrieval, and text extraction. "
        "Use list/search tools to find candidate filings, then use download/read tools to answer user questions with evidence."
    ),
)

_COMPANY_ALIASES: dict[str, list[str]] = {
    "노무라": ["野村", "Nomura", "野村アセットマネジメント"],
    "미즈호": ["みずほ", "Mizuho", "みずほ証券", "みずほ銀行"],
    "미쓰이스미토모": ["三井住友", "SMBC", "三井住友ＤＳ"],
    "미쓰비시ufj": ["三菱UFJ", "MUFG", "三菱ＵＦＪ"],
    "다이와": ["大和", "Daiwa", "大和証券"],
    "닛코": ["日興", "Nikko", "ＳＭＢＣ日興"],
    "소프트뱅크": ["ソフトバンク", "SoftBank"],
    "도요타": ["トヨタ", "Toyota"],
    "sony": ["ソニー", "Sony"],
}


def _extract_terms(question: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9가-힣一-龥ァ-ンぁ-ん]{2,}", question)
    stop = {
        "edinet",
        "api",
        "문서",
        "서류",
        "조회",
        "질문",
        "내용",
        "요약",
        "알려줘",
        "알려",
        "latest",
        "recent",
        "today",
        "yesterday",
        "this",
        "week",
        "최근",
        "관련",
        "제출",
        "제출된",
        "핵심",
        "요약",
        "요약해줘",
        "찾아줘",
        "보여줘",
    }
    terms: list[str] = []
    for t in raw:
        t = re.sub(r"(의|은|는|이|가|을|를|와|과|에|에서|으로|로|만)$", "", t)
        if len(t) < 2:
            continue
        k = t.lower()
        if k in stop:
            continue
        if t not in terms:
            terms.append(t)
    return terms


def _infer_requested_count(question: str, default_count: int = 8) -> int:
    m = re.search(r"(\d+)\s*건", question)
    if m:
        try:
            n = int(m.group(1))
            return max(1, min(30, n))
        except ValueError:
            return default_count
    return default_count


def _expand_company_hints(question: str, terms: list[str]) -> list[str]:
    q = question.lower()
    hints: list[str] = []

    for key, aliases in _COMPANY_ALIASES.items():
        if key in q:
            for alias in aliases:
                if alias not in hints:
                    hints.append(alias)

    for t in terms:
        if len(t) < 2:
            continue
        if t not in hints:
            hints.append(t)
    return hints


def _infer_date_range(question: str, from_date: str, to_date: str) -> tuple[str, str]:
    if from_date and to_date:
        return from_date, to_date

    iso_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)
    if len(iso_dates) >= 2:
        return iso_dates[0], iso_dates[1]
    if len(iso_dates) == 1:
        return iso_dates[0], iso_dates[0]

    today = dt.date.today()
    q = question.lower()
    m_year = re.search(r"최근\s*(\d+)\s*년", q)
    if m_year:
        years = max(1, int(m_year.group(1)))
        return (today - dt.timedelta(days=365 * years)).isoformat(), today.isoformat()
    m_month = re.search(r"최근\s*(\d+)\s*(개월|달)", q)
    if m_month:
        months = max(1, int(m_month.group(1)))
        return (today - dt.timedelta(days=30 * months)).isoformat(), today.isoformat()
    m_week = re.search(r"최근\s*(\d+)\s*주", q)
    if m_week:
        weeks = max(1, int(m_week.group(1)))
        return (today - dt.timedelta(days=7 * weeks)).isoformat(), today.isoformat()
    m_day = re.search(r"최근\s*(\d+)\s*일", q)
    if m_day:
        days = max(1, int(m_day.group(1)))
        return (today - dt.timedelta(days=days)).isoformat(), today.isoformat()

    if any(t in q for t in ["어제", "yesterday"]):
        d = today - dt.timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if any(t in q for t in ["오늘", "금일", "today"]):
        return today.isoformat(), today.isoformat()
    if any(t in q for t in ["이번주", "this week"]):
        start = today - dt.timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    if any(t in q for t in ["최근", "latest", "recent"]):
        start = today - dt.timedelta(days=2)
        return start.isoformat(), today.isoformat()

    start = today - dt.timedelta(days=7)
    return start.isoformat(), today.isoformat()


def _score_row(row: dict[str, Any], terms: list[str]) -> int:
    score = 0
    desc = str(row.get("docDescription", ""))
    filer = str(row.get("filerName", ""))
    for t in terms:
        t_lc = t.lower()
        if t_lc in desc.lower():
            score += 3
        if t_lc in filer.lower():
            score += 4
    if str(row.get("xbrlFlag", "0")) == "1":
        score += 2
    if str(row.get("pdfFlag", "0")) == "1":
        score += 1
    return score


def _collect_rows_in_range(
    from_date: str,
    to_date: str,
    cap: int = 30000,
    newest_first: bool = True,
) -> tuple[list[dict[str, Any]], int, bool]:
    start = dt.datetime.strptime(from_date, "%Y-%m-%d").date()
    end = dt.datetime.strptime(to_date, "%Y-%m-%d").date()
    rows: list[dict[str, Any]] = []
    scanned_dates = 0

    day = end if newest_first else start
    while (day >= start) if newest_first else (day <= end):
        scanned_dates += 1
        payload = edinet.list_documents(date=day.isoformat(), include_documents=True)
        chunk = payload.get("results") or []
        if isinstance(chunk, list):
            for r in chunk:
                if isinstance(r, dict):
                    rows.append(r)
                if len(rows) >= cap:
                    return rows, scanned_dates, True
        day += dt.timedelta(days=-1 if newest_first else 1)

    return rows, scanned_dates, False


def _extract_target_edinet_from_codelist(sec_code: str) -> set[str]:
    targets: set[str] = set()
    try:
        payload = codelist.search_rows(keyword=sec_code, kind="edinet", lang="ja", limit=200)
    except Exception:
        return targets

    for row in payload.get("results", []):
        if not isinstance(row, dict):
            continue
        blob = " ".join(str(v) for v in row.values() if v is not None)
        sec_hits = re.findall(r"(?<!\d)(\d{4,5})(?!\d)", blob)
        if sec_hits and not any(s.startswith(sec_code) or sec_code.startswith(s) for s in sec_hits):
            continue
        for e in re.findall(r"\bE\d{5}\b", blob, flags=re.IGNORECASE):
            targets.add(e.upper())
    return targets


def _collect_filtered_rows_in_range(
    from_date: str,
    to_date: str,
    *,
    newest_first: bool = True,
    keep_fn: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    start = dt.datetime.strptime(from_date, "%Y-%m-%d").date()
    end = dt.datetime.strptime(to_date, "%Y-%m-%d").date()
    rows: list[dict[str, Any]] = []
    scanned_dates = 0

    day = end if newest_first else start
    while (day >= start) if newest_first else (day <= end):
        scanned_dates += 1
        payload = edinet.list_documents(date=day.isoformat(), include_documents=True)
        chunk = payload.get("results") or []
        if isinstance(chunk, list):
            for r in chunk:
                if not isinstance(r, dict):
                    continue
                if keep_fn is None or keep_fn(r):
                    rows.append(r)
        day += dt.timedelta(days=-1 if newest_first else 1)
    return rows, scanned_dates


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    for n in needles:
        if n and n.lower() in h:
            return True
    return False


def _pick_source_type(row: dict[str, Any]) -> int:
    if str(row.get("xbrlFlag", "0")) == "1":
        return 1
    if str(row.get("pdfFlag", "0")) == "1":
        return 2
    if str(row.get("attachDocFlag", "0")) == "1":
        return 3
    if str(row.get("englishDocFlag", "0")) == "1":
        return 4
    if str(row.get("csvFlag", "0")) == "1":
        return 5
    return 2


def _make_snippet(text: str, terms: list[str], max_len: int = 380) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""

    if not terms:
        return compact[:max_len]

    low = compact.lower()
    for t in terms:
        pos = low.find(t.lower())
        if pos >= 0:
            start = max(0, pos - 120)
            end = min(len(compact), pos + 260)
            return compact[start:end]
    return compact[:max_len]


def _build_narrative_answer(
    question: str,
    interpreted: dict[str, Any],
    candidates: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    if not candidates:
        return (
            f"질문: {question}\n"
            f"- 조회기간: {interpreted.get('from_date')} ~ {interpreted.get('to_date')}\n"
            "- 조건에 맞는 공시를 찾지 못했습니다. 기간을 넓히거나 기업 식별자(증권코드/EDINET 코드)를 명시해 주세요."
        )

    lines = [
        f"질문: {question}",
        f"- 조회기간: {interpreted.get('from_date')} ~ {interpreted.get('to_date')}",
        f"- 추출 건수: {len(candidates)}건",
        "- 핵심 결과:",
    ]
    for i, c in enumerate(candidates[:5], start=1):
        lines.append(
            f"  {i}. {c.get('submitDateTime')} | {c.get('docID')} | {c.get('docDescription')} | 제출자 {c.get('filerName')}"
        )

    if evidence:
        lines.append("- 본문 근거:")
        for e in evidence[:3]:
            snippet = str(e.get("snippet", "")).strip()
            if snippet:
                lines.append(f"  - {e.get('docID')}: {snippet[:220]}")
    return "\n".join(lines)


@mcp.tool
def edinet_health_check(date: str = "") -> dict[str, Any]:
    """Check EDINET connectivity and API-key validity with a metadata request."""
    target = date.strip() or dt.date.today().isoformat()
    payload = edinet.list_documents(date=target, include_documents=False)
    metadata = payload.get("metadata", {})
    return {
        "ok": True,
        "date": target,
        "status": metadata.get("status"),
        "message": metadata.get("message"),
        "processDateTime": metadata.get("processDateTime"),
    }


@mcp.tool
def edinet_list_documents(date: str, include_documents: bool = True) -> dict[str, Any]:
    """Get EDINET metadata or full filing list for a specific YYYY-MM-DD date."""
    return edinet.list_documents(date=date, include_documents=include_documents)


@mcp.tool
def edinet_search_documents(
    from_date: str,
    to_date: str,
    query: str = "",
    edinet_code: str = "",
    sec_code: str = "",
    doc_type_code: str = "",
    ordinance_code: str = "",
    form_code: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Search filings across a date range using text and code filters."""
    return edinet.search_documents(
        from_date=from_date,
        to_date=to_date,
        query=query,
        edinet_code=edinet_code,
        sec_code=sec_code,
        doc_type_code=doc_type_code,
        ordinance_code=ordinance_code,
        form_code=form_code,
        limit=limit,
    )


@mcp.tool
def edinet_get_latest_documents(days: int = 3, limit: int = 100) -> dict[str, Any]:
    """Collect the latest filings in the last N days (including today)."""
    if days < 1:
        raise ValueError("days must be >= 1")
    if days > 31:
        raise ValueError("days must be <= 31")

    end = dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    return edinet.search_documents(from_date=start.isoformat(), to_date=end.isoformat(), limit=limit)


@mcp.tool
def edinet_download_document(
    doc_id: str,
    doc_type: int = 2,
    save_dir: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Download filing data by doc_id and type (1:zip-xbrl, 2:pdf, 3:attach zip, 4:english zip, 5:csv zip)."""
    result = edinet.download_document(doc_id=doc_id, doc_type=doc_type, save_dir=save_dir or None, overwrite=overwrite)
    return {
        "doc_id": result.doc_id,
        "doc_type": result.doc_type,
        "content_type": result.content_type,
        "file_path": str(result.file_path),
        "size_bytes": result.size_bytes,
    }


@mcp.tool
def edinet_read_document_text(doc_id: str, source_type: int = 1, max_chars: int = 30000) -> dict[str, Any]:
    """Extract plain text from a filing binary. source_type 1/3/4/5 for ZIP, 2 for PDF."""
    blob, content_type = edinet.get_document_binary(doc_id=doc_id, doc_type=source_type)

    if source_type == 2:
        text = extract_text_from_pdf_bytes(blob, max_chars=max_chars)
        return {
            "doc_id": doc_id,
            "source_type": source_type,
            "content_type": content_type,
            "text": text,
            "truncated": len(text) >= max_chars,
        }

    parsed = extract_text_from_zip_bytes(blob, max_chars=max_chars)
    return {
        "doc_id": doc_id,
        "source_type": source_type,
        "content_type": content_type,
        "parsed_files": parsed["parsed_files"],
        "truncated": parsed["truncated"],
        "text": parsed["text"],
    }


@mcp.tool
def edinet_load_code_list(
    kind: str = "edinet",
    lang: str = "ja",
    force_refresh: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Load EDINET/Fund code list CSV from official ZIP and return rows preview."""
    payload = codelist.load_rows(kind=kind, lang=lang, force_refresh=force_refresh)
    rows = payload["rows"]
    return {
        "kind": payload["kind"],
        "lang": payload["lang"],
        "csv_file": payload["csv_file"],
        "columns": payload["columns"],
        "row_count": payload["row_count"],
        "cache_zip": payload["cache_zip"],
        "preview": rows[:limit],
    }


@mcp.tool
def edinet_search_code_list(
    keyword: str,
    kind: str = "edinet",
    lang: str = "ja",
    field: str = "",
    limit: int = 20,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Search in EDINET/Fund code list by keyword, optionally scoped to a specific field."""
    return codelist.search_rows(
        keyword=keyword,
        kind=kind,
        lang=lang,
        field=field,
        limit=limit,
        force_refresh=force_refresh,
    )


@mcp.tool
def edinet_plan_query(question: str) -> dict[str, Any]:
    """Return a suggested tool sequence for arbitrary EDINET questions."""
    q = question.strip().lower()
    steps = []

    if any(token in q for token in ["latest", "최근", "today", "금일", "어제", "yesterday"]):
        steps.append("Use edinet_get_latest_documents(days=1..3) to gather candidate filings.")
    else:
        steps.append("Use edinet_search_documents(from_date, to_date, query=...) to narrow candidates.")

    if any(token in q for token in ["code", "코드", "edinet code", "증권코드", "회사코드"]):
        steps.append("Use edinet_search_code_list(keyword=...) to map organization names and codes.")

    if any(token in q for token in ["pdf", "본문", "내용", "what does", "무슨 내용", "xbrl", "csv"]):
        steps.append("Use edinet_read_document_text(doc_id, source_type) to extract searchable text.")
    else:
        steps.append("Use edinet_download_document(doc_id, doc_type=2) for raw file retrieval when needed.")

    steps.append("Cite docID, submitDateTime, filerName, and docDescription in final answer.")

    return {"question": question, "suggested_steps": steps}


@mcp.tool
def edinet_answer_question(
    question: str,
    from_date: str = "",
    to_date: str = "",
    max_candidates: int = 8,
    read_text: bool = True,
    max_text_docs: int = 3,
    max_chars_per_doc: int = 3000,
) -> dict[str, Any]:
    """Orchestrate search/code-mapping/text-read automatically for arbitrary EDINET questions."""
    if not question.strip():
        raise ValueError("question is required")

    if max_candidates < 1 or max_candidates > 30:
        raise ValueError("max_candidates must be between 1 and 30")
    if max_text_docs < 0 or max_text_docs > 10:
        raise ValueError("max_text_docs must be between 0 and 10")

    terms = _extract_terms(question)
    max_candidates = _infer_requested_count(question, default_count=max_candidates)
    company_hints = _expand_company_hints(question, terms)
    from_d, to_d = _infer_date_range(question, from_date, to_date)

    explicit_edinet = re.findall(r"\bE\d{5}\b", question, flags=re.IGNORECASE)
    explicit_sec = re.findall(r"(?<!\d)(\d{4,5})(?!\d)", question)
    edinet_code = explicit_edinet[0].upper() if explicit_edinet else ""
    sec_code = explicit_sec[0] if explicit_sec else ""
    q_lower = question.lower()
    shareholding_intent = any(
        k in q_lower
        for k in [
            "지분",
            "지분신고",
            "대량보유",
            "변경보고",
            "大量保有",
            "変更報告",
            "350",
            "360",
        ]
    )
    forced_doc_types = {"350", "360"} if shareholding_intent else set()

    # For shareholding queries with ticker-like code, default to 1 year unless user gave explicit dates.
    if shareholding_intent and sec_code and not from_date and not to_date and not re.search(r"\b\d{4}-\d{2}-\d{2}\b", question):
        from_d = (dt.date.today() - dt.timedelta(days=365)).isoformat()
        to_d = dt.date.today().isoformat()

    # Build target entity set from explicit inputs and sec-code inferred mapping.
    target_edinet_codes: set[str] = set()
    if edinet_code:
        target_edinet_codes.add(edinet_code)

    if sec_code:
        target_edinet_codes |= _extract_target_edinet_from_codelist(sec_code)

    need_targeted_scan = bool(shareholding_intent or sec_code or edinet_code)

    if need_targeted_scan:
        def keep_fn(r: dict[str, Any]) -> bool:
            if forced_doc_types and str(r.get("docTypeCode", "")) not in forced_doc_types:
                return False
            row_edinet = str(r.get("edinetCode", "") or "").upper()
            row_issuer = str(r.get("issuerEdinetCode", "") or "").upper()
            row_subject = str(r.get("subjectEdinetCode", "") or "").upper()
            row_sec = str(r.get("secCode", "") or "")
            if target_edinet_codes and (
                row_edinet in target_edinet_codes or row_issuer in target_edinet_codes or row_subject in target_edinet_codes
            ):
                return True
            if sec_code and row_sec.startswith(sec_code):
                return True
            return not (target_edinet_codes or sec_code)

        rows, scanned_dates = _collect_filtered_rows_in_range(from_d, to_d, newest_first=True, keep_fn=keep_fn)
        all_rows = rows
        scan_truncated = False
    else:
        all_rows, scanned_dates, scan_truncated = _collect_rows_in_range(from_d, to_d, cap=30000, newest_first=True)
        rows = all_rows
        if forced_doc_types:
            rows = [r for r in rows if str(r.get("docTypeCode", "")) in forced_doc_types]

    # Add inferred filer EDINET codes from rows with matching security code.
    if sec_code:
        for r in all_rows:
            row_sec = str(r.get("secCode", "") or "")
            row_edinet = str(r.get("edinetCode", "") or "").upper()
            if row_sec.startswith(sec_code) and row_edinet:
                target_edinet_codes.add(row_edinet)

    if target_edinet_codes or sec_code:
        narrowed = []
        for r in rows:
            row_edinet = str(r.get("edinetCode", "") or "").upper()
            row_issuer = str(r.get("issuerEdinetCode", "") or "").upper()
            row_subject = str(r.get("subjectEdinetCode", "") or "").upper()
            row_sec = str(r.get("secCode", "") or "")
            if (
                row_edinet in target_edinet_codes
                or row_issuer in target_edinet_codes
                or row_subject in target_edinet_codes
                or (sec_code and row_sec.startswith(sec_code))
            ):
                narrowed.append(r)
        rows = narrowed

    if company_hints:
        narrowed = []
        for r in rows:
            haystack = " ".join(
                [
                    str(r.get("filerName", "")),
                    str(r.get("docDescription", "")),
                    str(r.get("docID", "")),
                    str(r.get("edinetCode", "")),
                    str(r.get("issuerEdinetCode", "")),
                    str(r.get("subjectEdinetCode", "")),
                    str(r.get("secCode", "")),
                ]
            )
            if _contains_any(haystack, company_hints):
                narrowed.append(r)
        if narrowed:
            rows = narrowed

    ranked = sorted(
        [r for r in rows if isinstance(r, dict)],
        key=lambda r: (_score_row(r, company_hints), str(r.get("submitDateTime", ""))),
        reverse=True,
    )
    top = ranked[:max_candidates]

    wants_code_mapping = any(k in question.lower() for k in ["코드", "code", "edinet code", "증권코드"])
    code_candidates: list[dict[str, Any]] = []
    if wants_code_mapping and terms:
        for t in terms[:3]:
            try:
                found = codelist.search_rows(keyword=t, kind="edinet", lang="ja", limit=5)
            except Exception:
                continue
            for row in found.get("results", []):
                if row not in code_candidates:
                    code_candidates.append(row)
            if code_candidates:
                break

    evidence: list[dict[str, Any]] = []
    if read_text and max_text_docs > 0:
        for row in top[:max_text_docs]:
            doc_id = str(row.get("docID", "")).strip()
            if not doc_id:
                continue
            source_type = _pick_source_type(row)
            try:
                extracted = edinet_read_document_text(
                    doc_id=doc_id,
                    source_type=source_type,
                    max_chars=max_chars_per_doc,
                )
            except Exception as exc:
                evidence.append(
                    {
                        "docID": doc_id,
                        "source_type": source_type,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue

            snippet = _make_snippet(str(extracted.get("text", "")), terms)
            evidence.append(
                {
                    "docID": doc_id,
                    "source_type": source_type,
                    "content_type": extracted.get("content_type"),
                    "truncated": extracted.get("truncated"),
                    "snippet": snippet,
                    "parsed_files": extracted.get("parsed_files", [])[:5],
                }
            )

    candidates = [
        {
            "docID": r.get("docID"),
            "filerName": r.get("filerName"),
            "docDescription": r.get("docDescription"),
            "submitDateTime": r.get("submitDateTime"),
            "edinetCode": r.get("edinetCode"),
            "issuerEdinetCode": r.get("issuerEdinetCode"),
            "subjectEdinetCode": r.get("subjectEdinetCode"),
            "secCode": r.get("secCode"),
            "docTypeCode": r.get("docTypeCode"),
            "xbrlFlag": r.get("xbrlFlag"),
            "pdfFlag": r.get("pdfFlag"),
            "csvFlag": r.get("csvFlag"),
        }
        for r in top
    ]

    interpreted = {
        "from_date": from_d,
        "to_date": to_d,
        "terms": terms,
        "company_hints": company_hints,
        "edinet_code": edinet_code,
        "sec_code": sec_code,
        "target_edinet_codes": sorted(target_edinet_codes),
        "shareholding_intent": shareholding_intent,
        "forced_doc_types": sorted(forced_doc_types),
        "query_used": "",
        "wants_code_mapping": wants_code_mapping,
    }
    narrative = _build_narrative_answer(
        question=question,
        interpreted=interpreted,
        candidates=candidates,
        evidence=evidence,
    )

    return {
        "question": question,
        "answer": narrative,
        "interpreted": interpreted,
        "search_summary": {
            "scanned_dates": scanned_dates,
            "raw_count": len(rows),
            "truncated": scan_truncated,
        },
        "code_candidates": code_candidates[:10],
        "candidates": candidates,
        "evidence": evidence,
        "next_actions": [
            "Use docID from candidates to call edinet_download_document for original files.",
            "Increase date range or adjust question keywords when no candidates are returned.",
        ],
    }


@mcp.prompt
def edinet_analysis_prompt(question: str, from_date: str = "", to_date: str = "") -> str:
    """Prompt template to analyze an EDINET question with tool-grounded evidence."""
    return (
        "You are analyzing an EDINET question. "
        "First map company names/codes if needed, then search filings, then inspect primary documents. "
        "Question: "
        f"{question}\n"
        f"Date hint: from={from_date or 'auto'} to={to_date or 'auto'}\n"
        "Output should include evidence rows: docID, filerName, submitDateTime, docDescription."
    )


def _close_clients() -> None:
    try:
        edinet.close()
    finally:
        codelist.close()


if __name__ == "__main__":
    try:
        mcp.run()
    except EdinetApiError:
        raise
    finally:
        _close_clients()
