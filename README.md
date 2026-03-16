# edinet-mcp

EDINET API v2 기반 MCP 서버입니다.  
공시 목록 조회, 조건 검색, 원문 다운로드, 본문 텍스트 추출, 코드리스트 매핑, 질의형 분석을 하나의 MCP로 제공합니다.

## 주요 기능

- 날짜별 공시 목록 조회
- 기간/코드/문서종류 기반 검색
- 제출문서(PDF/ZIP 등) 다운로드
- PDF/ZIP(XBRL/HTML/XML/CSV) 텍스트 추출
- EDINET/Fund 코드리스트 로드/검색
- 질의형 분석(`edinet_plan_query`, `edinet_answer_question`)

## 요구 사항

- Python 3.10+
- EDINET API Key

## 빠른 시작

```bash
git clone <your-repo-url>
cd edinet-mcp

python3 -m venv env
./env/bin/pip install -r requirements.txt

cp .env.example .env
# .env 파일에서 EDINET_API_KEY 값을 실제 키로 변경
```

서버 실행:

```bash
./env/bin/python src/server.py
```

## OpenCode MCP 등록 예시

`~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "edinet-mcp": {
      "type": "local",
      "enabled": true,
      "command": [
        "/ABSOLUTE/PATH/edinet-mcp/env/bin/python",
        "/ABSOLUTE/PATH/edinet-mcp/src/server.py"
      ]
    }
  }
}
```

주의:

- `command`는 문자열이 아니라 **문자열 배열**이어야 합니다.
- `.env`를 사용하려면 서버 실행 시 작업 디렉터리가 프로젝트 루트여야 합니다.

## 환경변수

`.env` 또는 OS 환경변수로 설정할 수 있습니다.

- `EDINET_API_KEY` (필수): EDINET API Key
- `EDINET_API_BASE_URL` (선택, 기본값 `https://api.edinet-fsa.go.jp`)
- `EDINET_USER_AGENT` (선택, 기본값 `edinet-mcp/0.1`)
- `EDINET_TIMEOUT_SECONDS` (선택, 기본값 `30`)
- `EDINET_CACHE_DIR` (선택, 기본값 `.cache`)
- `EDINET_DOWNLOAD_DIR` (선택, 기본값 `downloads`)

## 제공 도구

- `edinet_health_check(date="")`
- `edinet_list_documents(date, include_documents=True)`
- `edinet_search_documents(from_date, to_date, query="", edinet_code="", sec_code="", doc_type_code="", ordinance_code="", form_code="", limit=50)`
- `edinet_get_latest_documents(days=3, limit=100)`
- `edinet_download_document(doc_id, doc_type=2, save_dir="", overwrite=False)`
- `edinet_read_document_text(doc_id, source_type=1, max_chars=30000)`
- `edinet_load_code_list(kind="edinet", lang="ja", force_refresh=False, limit=200)`
- `edinet_search_code_list(keyword, kind="edinet", lang="ja", field="", limit=20, force_refresh=False)`
- `edinet_plan_query(question)`
- `edinet_answer_question(question, from_date="", to_date="", max_candidates=8, read_text=True, max_text_docs=3, max_chars_per_doc=3000)`

## 구현 메모

- EDINET은 실패 상황에서도 HTTP 200을 반환할 수 있어, 응답 JSON 내부 `status/statusCode`를 함께 검사합니다.
- 다운로드 성공 여부는 `Content-Type` 기반으로 판단합니다.
- ZIP 문서는 내부 XBRL/XML/HTML/CSV를 순회해 텍스트를 추출합니다.
- PDF 추출은 `pypdf`를 사용합니다.

## 문제 해결

- `EDINET_API_KEY is not set`:
  - `.env` 파일 위치가 프로젝트 루트인지 확인
  - 키 오탈자 및 공백 포함 여부 확인
- `401` 응답:
  - API 키 만료/오입력 가능성 확인
- 대량 조회 시 느림/실패:
  - `from_date ~ to_date`를 더 작은 구간으로 나눠 요청

## 보안 가이드

- `.env`는 커밋하지 마세요.
- 키는 코드/설정 파일에 하드코딩하지 마세요.
- 공개 저장소에는 `.env.example`만 포함하세요.
