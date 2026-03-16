# edinet-mcp

`edinet-mcp`는 EDINET API v2를 MCP 서버로 감싼 프로젝트입니다.  
다운로드한 뒤 Python 환경만 준비하면 MCP 클라이언트에서 바로 공시 조회, 문서 다운로드, 본문 텍스트 추출을 사용할 수 있습니다.

## 무엇을 할 수 있나요?

- 특정 날짜의 공시 목록 조회
- 기간별 공시 검색
- `docID` 기준 원문(PDF/ZIP) 다운로드
- PDF, XBRL ZIP, CSV ZIP의 텍스트 추출
- EDINET/Fund 코드리스트 조회 및 검색
- 자연어 질문 기반 후보 문서 탐색

## 사용 전 준비

- Python 3.10 이상
- EDINET API Key

## 설치

```bash
git clone <your-repo-url>
cd edinet-mcp

python3 -m venv env
./env/bin/pip install -r requirements.txt
cp .env.example .env
```

`.env` 파일에서 `EDINET_API_KEY`를 실제 키로 바꿔주세요.

## 실행

프로젝트 루트에서 아래처럼 실행하면 됩니다.

```bash
./env/bin/python src/server.py
```

이 서버는 `.env`를 현재 작업 디렉터리 기준으로 읽기 때문에, 프로젝트 루트에서 실행하는 것이 안전합니다.

## MCP에 등록하기

예시: `~/.config/opencode/opencode.json`

```json
{
  "mcp": {
    "edinet-mcp": {
      "type": "local",
      "enabled": true,
      "command": [
        "/ABSOLUTE/PATH/edinet-mcp/env/bin/python",
        "/ABSOLUTE/PATH/edinet-mcp/src/server.py"
      ],
      "cwd": "/ABSOLUTE/PATH/edinet-mcp"
    }
  }
}
```

중요한 점:

- `command`는 문자열 하나가 아니라 문자열 배열이어야 합니다.
- `cwd`를 프로젝트 루트로 지정해야 `.env`를 안정적으로 읽습니다.

## 자주 쓰는 도구

- `edinet_health_check`: API 키와 연결 상태 확인
- `edinet_list_documents`: 특정 날짜 공시 목록 조회
- `edinet_search_documents`: 기간 조건으로 공시 검색
- `edinet_get_latest_documents`: 최근 며칠치 공시 조회
- `edinet_download_document`: 문서 원본 저장
- `edinet_read_document_text`: 문서 본문 텍스트 추출
- `edinet_search_code_list`: 회사명이나 코드 검색
- `edinet_answer_question`: 자연어 질문으로 후보 문서와 근거 찾기

## 환경변수

- `EDINET_API_KEY`: 필수
- `EDINET_API_BASE_URL`: 기본값 `https://api.edinet-fsa.go.jp`
- `EDINET_USER_AGENT`: 기본값 `edinet-mcp/0.1`
- `EDINET_TIMEOUT_SECONDS`: 기본값 `30`
- `EDINET_CACHE_DIR`: 기본값 `.cache`
- `EDINET_DOWNLOAD_DIR`: 기본값 `downloads`

## 사용 흐름 예시

보통은 아래 순서로 사용하면 됩니다.

1. `edinet_health_check`로 연결 확인
2. `edinet_search_documents` 또는 `edinet_get_latest_documents`로 후보 찾기
3. 필요한 문서의 `docID` 확인
4. `edinet_download_document` 또는 `edinet_read_document_text` 호출

질문형 탐색이 필요하면 `edinet_answer_question`을 바로 사용해도 됩니다.

## 문제 해결

- `EDINET_API_KEY is not set`
  - `.env`가 프로젝트 루트에 있는지 확인
  - 키 앞뒤 공백이 없는지 확인
- `401` 또는 인증 오류
  - API 키가 유효한지 확인
- 문서가 안 내려받아짐
  - `doc_id`, `doc_type` 값이 맞는지 확인
- 검색 범위가 너무 넓어 느림
  - 날짜 범위를 더 짧게 나눠서 조회

## 참고

- 다운로드 파일은 기본적으로 `downloads/` 아래에 저장됩니다.
- 캐시 파일은 기본적으로 `.cache/` 아래에 저장됩니다.
- `.env`는 저장소에 커밋하지 않도록 유지하세요.
