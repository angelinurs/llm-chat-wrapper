import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.config import settings
from app.db import init_db
from app.errors import AppException, ErrorCode, register_exception_handlers
from app.graph import build_graph
from app.schemas import (
    ChatRequest,
    ChatResponse,
    CommonResponse,
    HealthData,
    HistoryMessage,
    HistoryResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.llm_debug:  # LLM 입출력 전문을 콘솔에 출력 (개발용)
        from langchain.globals import set_debug

        set_debug(True)
    init_db()  # DuckDB 생성 + Flyway 식 마이그레이션 적용
    app.state.graph = build_graph()
    yield


app = FastAPI(title="LLM Wrapper Service", lifespan=lifespan)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=CommonResponse[HealthData])
async def health() -> CommonResponse[HealthData]:
    return CommonResponse.ok(
        HealthData(status="ok", llm_model=settings.llm_model or "(echo stub)")
    )


@app.post("/api/chat", response_model=CommonResponse[ChatResponse])
async def chat(req: ChatRequest) -> CommonResponse[ChatResponse]:
    graph = app.state.graph
    config = {"configurable": {"thread_id": req.session_id}}

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=req.message)]}, config
        )
    except Exception as e:  # LLM/도구 호출 실패 → 전역 핸들러가 502로 변환
        raise AppException(ErrorCode.LLM_SERVICE_ERROR, str(e)) from e

    messages = result["messages"]
    reply = next(
        (
            m.content
            for m in reversed(messages)
            if isinstance(m, AIMessage) and m.content
        ),
        "",
    )

    # 이번 턴에서 사용된 도구 수집: 마지막 HumanMessage 이후의 tool call들
    tools_used: list[str] = []
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage):
            tools_used = [tc["name"] for tc in m.tool_calls] + tools_used

    return CommonResponse.ok(
        ChatResponse(session_id=req.session_id, reply=reply, tools_used=tools_used)
    )


def _chunk_text(content: Any) -> str:
    """메시지 청크 content에서 텍스트만 추출 (provider별 list 형식 대응)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 스트리밍 응답. 이벤트: token / tool / done / error"""
    graph = app.state.graph
    config = {"configurable": {"thread_id": req.session_id}}

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk, _metadata in graph.astream(
                {"messages": [HumanMessage(content=req.message)]},
                config,
                stream_mode="messages",
            ):
                if isinstance(chunk, ToolMessage):
                    yield sse({"type": "tool", "name": chunk.name})
                    # run_sql 결과는 LLM 을 거치지 않고 즉시 표로 전달
                    if chunk.name == "run_sql":
                        try:
                            data = json.loads(chunk.content)
                        except (json.JSONDecodeError, TypeError):
                            data = None
                        if isinstance(data, dict) and "columns" in data:
                            yield sse({"type": "table", **data})
                elif isinstance(chunk, AIMessage):
                    text = _chunk_text(chunk.content)
                    if text:
                        yield sse({"type": "token", "content": text})
            yield sse({"type": "done"})
        except Exception as e:
            exc = AppException(ErrorCode.LLM_SERVICE_ERROR, str(e))  # 로깅 포함
            yield sse(
                {
                    "type": "error",
                    "code": exc.error_code.code,
                    "message": exc.message,
                }
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/history/{session_id}", response_model=CommonResponse[HistoryResponse])
async def history(session_id: str) -> CommonResponse[HistoryResponse]:
    graph = app.state.graph
    state = await graph.aget_state({"configurable": {"thread_id": session_id}})
    messages = [
        HistoryMessage(role=m.type, content=str(m.content))
        for m in state.values.get("messages", [])
        if m.type in ("human", "ai") and m.content
    ]
    return CommonResponse.ok(HistoryResponse(session_id=session_id, messages=messages))
