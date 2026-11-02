# LLM Wrapper Service

LangGraph tool-calling 기반 LLM wrapper service.
FastAPI backend + Next.js frontend, 멀티턴 대화 지원.

## 구조

```
llm-wrapper-service/
├── backend/                  # FastAPI + LangGraph (uv, Python 3.11.11)
│   ├── app/
│   │   ├── main.py           # FastAPI 엔트리포인트 (/api/chat, /api/history, /api/health)
│   │   ├── graph.py          # LangGraph 에이전트 그래프 (agent ↔ tools 루프)
│   │   ├── llm.py            # 모델 팩토리 (LLM_MODEL env로 교체, 미설정 시 echo 스텁)
│   │   ├── tools.py          # tool-calling 도구 (현재 시간, 계산기 — 교체/추가 지점)
│   │   ├── config.py         # 환경변수 설정
│   │   └── schemas.py        # 요청/응답 모델
│   └── tests/
└── frontend/                 # Next.js (App Router) 채팅 UI
    └── app/page.tsx          # /api/* 는 next.config.mjs rewrites로 backend에 프록시
```

## 실행

### Backend (http://localhost:8000)

```bash
cd backend
uv sync                 # Python 3.11.11 venv 자동 생성 + 의존성 설치
cp .env.example .env    # 모델 선정 후 LLM_MODEL / API 키 설정
uv run uvicorn app.main:app --reload
```

### Frontend (http://localhost:3000)

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:3000 접속.

## 멀티턴 동작 방식

- frontend가 세션마다 `session_id`(UUID)를 생성해 `/api/chat`에 전달
- backend는 `session_id`를 LangGraph `thread_id`로 사용, `InMemorySaver` 체크포인터가 대화 이력을 유지
- 프로덕션 전환 시 `backend/app/graph.py`의 체크포인터를 `PostgresSaver`/`RedisSaver` 등으로 교체

## 모델 선정 (추후)

모델이 정해지면 `backend/.env`에 설정:

```bash
# 예시
LLM_MODEL=anthropic:claude-opus-5-5
ANTHROPIC_API_KEY=sk-ant-...
```

그리고 provider 패키지 설치:

```bash
cd backend
uv sync --extra anthropic   # 또는 --extra openai, --extra google
```

`LLM_MODEL`이 비어 있으면 echo 스텁 모드로 동작해 API 키 없이도 전체 파이프라인(멀티턴, UI 연동)을 확인할 수 있습니다. 단, tool call은 실제 모델 연결 후 동작합니다.

## 테스트

```bash
cd backend
uv run pytest
```
