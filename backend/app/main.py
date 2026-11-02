from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.graph import build_graph
from app.schemas import ChatRequest, ChatResponse, HistoryMessage, HistoryResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = build_graph()
    yield


app = FastAPI(title="LLM Wrapper Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "llm_model": settings.llm_model or "(echo stub)",
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    graph = app.state.graph
    config = {"configurable": {"thread_id": req.session_id}}

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=req.message)]}, config
        )
    except Exception as e:  # LLM/도구 호출 실패를 클라이언트에 전달
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {e}") from e

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

    return ChatResponse(session_id=req.session_id, reply=reply, tools_used=tools_used)


@app.get("/api/history/{session_id}", response_model=HistoryResponse)
async def history(session_id: str) -> HistoryResponse:
    graph = app.state.graph
    state = await graph.aget_state({"configurable": {"thread_id": session_id}})
    messages = [
        HistoryMessage(role=m.type, content=str(m.content))
        for m in state.values.get("messages", [])
        if m.type in ("human", "ai") and m.content
    ]
    return HistoryResponse(session_id=session_id, messages=messages)
