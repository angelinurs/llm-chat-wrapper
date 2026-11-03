# Backend — LLM Wrapper Service

FastAPI + LangGraph로 만든 채팅 API 서버입니다.
사용자가 질문을 보내면 → LLM이 (필요하면 도구를 써서) 답변을 만들어 돌려줍니다.
데이터 질문이 오면 LLM이 직접 SQL을 작성해 분석 DB(DuckDB)를 조회합니다 (text-to-SQL).

## 1. 전체 그림

```
사용자 질문
    │
    ▼
[FastAPI]  ──  HTTP 요청을 받는 창구 (main.py)
    │
    ▼
[LangGraph 그래프]  ──  "생각 → 도구 사용 → 다시 생각" 반복 (graph.py)
    │                      │
    │                      ├── agent 노드: LLM에게 물어봄 (llm.py)
    │                      └── tools 노드: 도구 실행 (tools.py)
    │                             ├─ 시계, 계산기
    │                             └─ 스키마 조회 + SQL 실행 ──▶ [DuckDB 분석 DB] (db.py)
    ▼
답변을 SSE 스트리밍으로 반환 (표 데이터는 table 이벤트로 즉시 전달)
```

## 2. 프로젝트 구조

```
backend/
├── pyproject.toml        # 의존성 목록 (uv가 읽는 파일. Java의 pom.xml 같은 역할)
├── .python-version       # Python 버전 고정 (3.11.11)
├── .env.example          # 환경변수 예시 (복사해서 .env 만들기)
│
├── migrations/           # Flyway 스타일 DB 마이그레이션 (이름순으로 자동 적용)
│   ├── V1__create_tables.sql   # customers / products / orders 스키마
│   └── V2__seed_data.sql       # 테스트용 시드 데이터
│
├── app/                  # 애플리케이션 코드
│   ├── main.py           # ① 시작점. API 엔드포인트 + SSE 스트리밍 (가장 먼저 읽을 파일)
│   ├── config.py         # ② 설정. .env 를 읽어 설정값으로 만듦 (LLM_MODEL, LLM_DEBUG 등)
│   ├── schemas.py        # ③ 데이터 모양 정의. CommonResponse envelope, 요청/응답 형식
│   ├── graph.py          # ④ 핵심 로직. LangGraph 에이전트 루프 조립 + 멀티턴 체크포인터
│   ├── llm.py            # ⑤ 모델 공장. 어떤 LLM을 쓸지 결정 (미설정 시 echo 스텁)
│   ├── tools.py          # ⑥ 도구 모음. LLM이 호출하는 함수들
│   ├── db.py             # ⑦ 분석 DB. DuckDB + 마이그레이션 러너 + 스키마 카탈로그
│   └── errors.py         # ⑧ 에러 처리. ErrorCode 표 + 전역 예외 핸들러
│
└── tests/                # 테스트 (uv run pytest — API 키 없이 echo 모드로 실행됨)
    ├── conftest.py       # 테스트는 항상 echo 스텁 모드로 강제 (실제 API 호출 방지)
    ├── test_chat.py      # 대화/멀티턴
    ├── test_stream.py    # SSE 스트리밍
    ├── test_errors.py    # 에러 응답 형식
    └── test_db.py        # 마이그레이션, SQL 검증, 스키마 카탈로그
```

**읽는 순서 추천**: `main.py` → `graph.py` → `tools.py` → `db.py` 순으로 보면 흐름이 잡힙니다.

## 3. 실행하기 (3단계)

```bash
# ① 의존성 설치 — Python 3.11.11 가상환경(.venv)까지 자동으로 만들어 줍니다
uv sync --extra anthropic    # Anthropic 모델 사용 시 (openai/google 도 가능)

# ② 환경변수 파일 만들기 (처음 한 번만)
cp .env.example .env         # LLM_MODEL 과 API 키 설정

# ③ 서버 실행 — 코드를 고치면 자동으로 재시작됩니다(--reload)
uv run uvicorn app.main:app --reload
```

실행 후 확인:

- http://localhost:8000/docs — **Swagger UI** (브라우저에서 API를 직접 눌러볼 수 있음)
- http://localhost:8000/api/health — 서버 상태 + 현재 모델 확인

> **모델(API 키)이 없어도 됩니다.** `.env`의 `LLM_MODEL`이 비어 있으면
> **echo 스텁 모드**로 동작해서, 입력을 그대로 돌려주는 가짜 LLM으로
> 전체 흐름을 테스트할 수 있습니다. 진짜 모델을 쓰려면:
> `LLM_MODEL=anthropic:claude-sonnet-5-5` + `ANTHROPIC_API_KEY=sk-ant-...`

## 4. API 한눈에 보기

| 메서드 | 경로 | 하는 일 |
| --- | --- | --- |
| POST | `/api/chat` | 질문 보내고 답변 받기 (완성된 답을 한 번에) |
| POST | `/api/chat/stream` | 답변을 **조각조각 스트리밍**으로 받기 (SSE) ← 프론트가 사용 |
| GET | `/api/history/{session_id}` | 그 세션의 대화 기록 보기 |
| GET | `/api/health` | 서버 살아있는지 + 현재 모델 확인 |

모든 단건 응답은 공통 봉투(**CommonResponse**)에 담겨 옵니다:

```json
{ "success": true, "code": "OK", "message": "", "data": { ... } }
```

SSE 스트림은 이벤트 단위 JSON 입니다:

| 이벤트 | 의미 |
| --- | --- |
| `{"type": "token", "content": "..."}` | 답변 텍스트 조각 (토큰 단위) |
| `{"type": "tool", "name": "run_sql"}` | 도구 실행됨 |
| `{"type": "table", "columns": [...], "rows": [...]}` | SQL 결과 표 (LLM을 거치지 않고 즉시 전달) |
| `{"type": "done"}` / `{"type": "error", ...}` | 종료 / 실패 |

## 5. 꼭 알아야 할 개념 4가지

**① 멀티턴 (대화 기억)**
같은 `session_id`로 요청하면 이전 대화를 기억합니다.
비밀은 LangGraph의 **checkpointer**: `session_id`를 `thread_id`로 사용해
대화 상태를 자동 저장/복원합니다 (`graph.py`). 지금은 메모리 저장이라
서버를 재시작하면 사라집니다.

**② tool calling (도구 호출)**
`tools.py`에 `@tool` 붙은 함수가 LLM의 능력이 됩니다. 함수 이름·docstring·타입
힌트가 자동으로 LLM용 명세로 변환되고, LLM이 필요하다고 판단하면 스스로
호출합니다. **docstring이 곧 사용설명서**라서 "언제/무엇을/어떤 입력으로"를
명확히 쓰는 것이 품질의 핵심입니다.

**③ text-to-SQL — 2단계 스키마 조회**
데이터 질문이 오면 LLM이 이 순서로 움직입니다 (시스템 프롬프트로 유도):

1. `list_tables` — 테이블 카탈로그(한 줄 설명) + **관계 지도(FK)** 확인
2. `get_table_details(["orders", ...])` — 필요한 테이블의 컬럼 상세만 조회
3. `run_sql` — JOIN/집계 SQL 작성·실행 (**SELECT만 허용, 최대 50행 강제**)

카탈로그를 작게 유지하고 상세는 선택분만 주기 때문에, 테이블이 늘어도 입력
토큰이 비례 증가하지 않습니다. SQL이 틀리면 에러 메시지가 LLM에게 돌아가
스스로 고쳐 재시도합니다. 결과 표는 LLM을 거치지 않고 `table` 이벤트로
화면에 바로 전달됩니다 (토큰 절약 + 숫자 환각 방지).

**④ 에러 처리 흐름**
어디서든 예외가 나면 → `errors.py`의 전역 핸들러가 잡아서 →
CommonResponse 형식으로 바꿔 응답합니다. 새 에러 종류는 `ErrorCode` enum에
한 줄 추가하고 `raise AppException(ErrorCode.XXX, "설명")` 하면 끝입니다.

## 6. 테스트

```bash
uv run pytest        # 전체 실행
uv run pytest -v     # 테스트 이름까지 자세히
```

`conftest.py`가 테스트 시작 전에 echo 스텁 모드로 강제하므로,
`.env`에 실제 모델이 설정되어 있어도 **API 호출(비용) 없이** 안전하게 돌 수 있습니다.

## 7. 디버깅 팁

LLM과 실제로 주고받는 내용(프롬프트 전문, tool call args)을 보고 싶으면:

```bash
# .env 에서
LLM_DEBUG=true
```

서버 재시작 후 매 LLM 호출의 입출력이 콘솔에 전부 출력됩니다 (출력이 많으니
디버깅할 때만). 더 제대로 보려면 LangSmith(환경변수 2줄) 같은 트레이싱 도구를
연결하면 호출 트리를 웹 UI에서 볼 수 있습니다.

## 8. 분석 DB 백엔드 전환 (DuckDB ↔ Oracle)

분석 DB는 `DB_BACKEND` 환경변수로 구현이 갈립니다. tool/그래프/프론트 코드는
어느 쪽이 꽂혀 있는지 모릅니다 (동일 인터페이스).

**설정 프로필 (Spring 의 profiles 대응)** — `config/application.yml`(공통) 위에
`application-{profile}.yml` 이 덮어쓰입니다. 우선순위:
환경변수 > .env > 프로필 yml > 공통 yml > 코드 기본값.

```bash
# 기본(local 프로필): DuckDB in-memory (마이그레이션·시드 자동 적용)
uv run uvicorn app.main:app --reload

# prod 프로필: application-prod.yml 적용 → Oracle 백엔드
# 접속 정보는 yml 이 아니라 환경변수(Secret)로 주입
APP_PROFILE=prod ORACLE_DSN=host:1521/SVC ORACLE_USER=ro ORACLE_PASSWORD=... \
  uv run uvicorn app.main:app

# 프로필과 무관하게 환경변수로 개별 설정을 덮어쓸 수도 있음
DB_BACKEND=oracle ORACLE_DSN=... uv run uvicorn app.main:app
```

| | duckdb (기본) | oracle |
| --- | --- | --- |
| 용도 | dev/테스트 대역 | 프로덕션 |
| 스키마 카탈로그 | 코드의 설명 dict | 데이터 딕셔너리 (TABLE/COLUMN COMMENT, FK 제약) 자동 생성 |
| 행수 제한 | `LIMIT` 래핑 | `FETCH FIRST n ROWS ONLY` 래핑 |
| 필요 패키지 | 기본 포함 | `uv sync --extra oracle` |

프로덕션(k8s)에서는 `ORACLE_*` 변수를 Secret 으로 주입하면 됩니다.
Oracle 카탈로그 품질은 DB 에 달린 COMMENT 충실도에 비례하므로,
테이블·컬럼 주석을 잘 달아두는 것이 text-to-SQL 정확도의 핵심입니다.
pytest 는 `conftest.py`가 항상 DuckDB 로 고정하므로 Oracle 없이 돌 수 있습니다.
