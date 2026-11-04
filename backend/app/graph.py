"""LangGraph tool-calling 에이전트 그래프.

구조:
  START → agent ─┬─ (일반 tool call) ────→ tools ──────────────→ agent
                 ├─ (parallel_sql 호출) → sql_worker × N ─→ collect → agent
                 │                         (Send API 병렬 실행)
                 └─ (tool call 없음) ───→ END

멀티턴: InMemorySaver 체크포인터 + thread_id(session_id).
병렬 실행: 모델이 parallel_sql 로 독립 쿼리 목록을 내면, 라우터가 Send 로
쿼리별 worker 를 같은 super-step 에 뿌려 동시에 실행하고 collect 가 합친다.
"""

import json
from typing import Annotated

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from app.config import settings
from app.db import run_select
from app.llm import get_chat_model
from app.tools import TOOLS


def _add_or_clear(old: list | None, new) -> list:
    """병렬 worker 결과 누적 리듀서. None 이 오면 초기화."""
    if new is None:
        return []
    return (old or []) + list(new)


class ChatState(MessagesState):
    sql_results: Annotated[list, _add_or_clear]


def route_after_agent(state: ChatState):
    """agent 응답의 tool call 에 따라 분기. parallel_sql 은 Send 로 병렬 fan-out."""
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    if not calls:
        return END
    for call in calls:
        if call["name"] == "parallel_sql":
            queries = call["args"].get("queries") or []
            if queries:
                return [
                    Send("sql_worker", {"index": i, "query": q})
                    for i, q in enumerate(queries)
                ]
    return "tools"


def sql_worker(payload: dict) -> dict:
    """쿼리 하나를 실행하는 병렬 worker (Send 1건 = worker 1개)."""
    try:
        result = run_select(payload["query"])
    except Exception as e:
        result = {"error": str(e)}
    return {
        "sql_results": [
            {"index": payload["index"], "query": payload["query"], "result": result}
        ]
    }


def collect(state: ChatState) -> dict:
    """fan-in: 병렬 결과를 하나의 ToolMessage 로 합쳐 agent 에 돌려준다."""
    last_ai = next(
        m
        for m in reversed(state["messages"])
        if isinstance(m, AIMessage) and m.tool_calls
    )
    ordered = sorted(state["sql_results"], key=lambda r: r["index"])
    content = json.dumps(
        [{"query": r["query"], "result": r["result"]} for r in ordered],
        ensure_ascii=False,
    )
    messages: list[ToolMessage] = []
    for call in last_ai.tool_calls:
        if call["name"] == "parallel_sql":
            messages.append(
                ToolMessage(
                    content=content, name="parallel_sql", tool_call_id=call["id"]
                )
            )
        else:  # 같은 턴에 섞여 온 다른 tool call 은 에러로 응답 (dangling 방지)
            messages.append(
                ToolMessage(
                    content="parallel_sql 은 다른 도구와 동시에 호출할 수 없습니다. "
                    "이 도구는 다음 턴에 단독으로 호출하세요.",
                    name=call["name"],
                    tool_call_id=call["id"],
                )
            )
    return {"messages": messages, "sql_results": None}


def build_graph() -> CompiledStateGraph:
    model = get_chat_model().bind_tools(TOOLS)

    def agent(state: ChatState) -> dict:
        messages = [SystemMessage(content=settings.system_prompt)] + state["messages"]
        return {"messages": [model.invoke(messages)]}

    builder = StateGraph(ChatState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node("sql_worker", sql_worker)
    builder.add_node("collect", collect)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", route_after_agent, ["tools", "sql_worker", END]
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("sql_worker", "collect")
    builder.add_edge("collect", "agent")

    # 프로덕션에서는 InMemorySaver 대신 PostgresSaver/RedisSaver 등으로 교체
    return builder.compile(checkpointer=InMemorySaver())
