# Backend — LLM Wrapper Service

FastAPI + LangGraph로 만든 채팅 API 서버입니다.
사용자가 질문을 보내면 → LLM이 (필요하면 도구를 써서) 답변을 만들어 돌려줍니다.

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
    │                      └── tools 노드: 계산기, 시계 같은 도구 실행 (tools.py)
    ▼
답변을 JSON 또는 SSE 스트리밍으로 반환
```

## 2. 프로젝트 구조

```
backend/
├── pyproject.toml        # 의존성 목록 (uv가 읽는 파일. Java의 pom.xml 같은 역할)
├── .python-version       # Python 버전 고정 (3.11.11)
├── .env.example          # 환경변수 예시 (복사해서 .env 만들기)
│
├── app/                  # 애플리케이션 코드
│   ├── main.py           # ① 시작점. API 엔드포인트 정의 (가장 먼저 읽을 파일)
│   ├── config.py         # ② 설정. .env 파일을 읽어서 설정값으로 만듦
│   ├── schemas.py        # ③ 데이터 모양 정의. 요청/응답 JSON의 형식 (CommonResponse)
│   ├── graph.py          # ④ 핵심 로직. LangGraph로 "에이전트 루프"를 조립
│   ├── llm.py            # ⑤ 모델 공장. 어떤 LLM을 쓸지 결정 (미설정 시 echo 스텁)
│   ├── tools.py          # ⑥ 도구 모음. LLM이 호출할 수 있는 함수들
│   └── errors.py         # ⑦ 에러 처리. 에러 코드표 + 전역 예외 핸들러
│
└── tests/                # 테스트 코드 (uv run pytest 로 실행)
    ├── test_chat.py      # 대화/멀티턴 테스트
    ├── test_errors.py    # 에러 응답 형식 테스트
    └── test_stream.py    # SSE 스트리밍 테스트
```

**읽는 순서 추천**: `main.py` → `graph.py` → `tools.py` → `llm.py` 순으로 보면 흐름이 잡힙니다.

## 3. 실행하기 (3단계)

```bash
# ① 의존성 설치 — Python 3.11.11 가상환경(.venv)까지 자동으로 만들어 줍니다
uv sync

# ② 환경변수 파일 만들기 (처음 한 번만)
cp .env.example .env

# ③ 서버 실행 — 코드를 고치면 자동으로 재시작됩니다(--reload)
uv run uvicorn app.main:app --reload
```

실행 후 확인:

- http://localhost:8000/docs — **Swagger UI** (브라우저에서 API를 직접 눌러볼 수 있음)
- http://localhost:8000/api/health — 서버 상태 확인

> **모델(API 키)이 없어도 됩니다.** `.env`의 `LLM_MODEL`이 비어 있으면
> **echo 스텁 모드**로 동작해서, 입력을 그대로 돌려주는 가짜 LLM으로
> 전체 흐름을 테스트할 수 있습니다. 진짜 모델을 쓰려면 `.env`에서
> `LLM_MODEL=anthropic:claude-opus-5-5` 처럼 설정하고 API 키를 넣으세요.

## 4. API 한눈에 보기

| 메서드 | 경로 | 하는 일 |
| --- | --- | --- |
| POST | `/api/chat` | 질문 보내고 답변 받기 (완성된 답을 한 번에) |
| POST | `/api/chat/stream` | 질문 보내고 답변을 **조각조각 스트리밍**으로 받기 (SSE) |
| GET | `/api/history/{session_id}` | 그 세션의 대화 기록 보기 |
| GET | `/api/health` | 서버 살아있는지 + 현재 모델 확인 |

### 요청/응답 예시

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc", "message": "안녕"}'
```

모든 응답은 공통 봉투(**CommonResponse**)에 담겨 옵니다:

```json
{ "success": true, "code": "OK", "message": "", "data": { "reply": "...", "tools_used": [] } }
```

실패하면 `success: false` + 에러 코드(`errors.py`의 ErrorCode 표 참고)가 옵니다.

## 5. 꼭 알아야 할 개념 3가지

**① 멀티턴 (대화 기억)**
같은 `session_id`로 요청하면 이전 대화를 기억합니다.
비밀은 LangGraph의 **checkpointer**: `session_id`를 `thread_id`로 사용해
대화 상태를 자동 저장/복원합니다 (`graph.py`). 지금은 메모리에 저장하므로
서버를 재시작하면 사라집니다.

**② tool calling (도구 호출)**
"지금 몇 시야?"라고 물으면 LLM이 스스로 `get_current_time` 도구를 호출하고,
그 결과를 보고 답변을 만듭니다. 도구는 `tools.py`에 `@tool` 붙은 함수로 정의하며,
여기에 함수를 추가하면 LLM이 쓸 수 있는 능력이 늘어납니다.

**③ 에러 처리 흐름**
어디서든 예외가 나면 → `errors.py`의 전역 핸들러가 잡아서 →
CommonResponse 형식으로 바꿔 응답합니다. 새 에러 종류가 필요하면
`ErrorCode` enum에 한 줄 추가하고 `raise AppException(ErrorCode.XXX, "설명")`
하면 끝입니다.

## 6. 테스트

```bash
uv run pytest        # 전체 실행
uv run pytest -v     # 테스트 이름까지 자세히
```

echo 스텁 모드로 돌기 때문에 API 키 없이 언제든 실행할 수 있습니다.
