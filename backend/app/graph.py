"""LangGraph tool-calling 에이전트 그래프.

구조:  START → agent → (tool call 있으면) tools → agent → ... → END
멀티턴: InMemorySaver 체크포인터 + thread_id(session_id)로 대화 이력을 유지한다.
"""

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.config import settings
from app.llm import get_chat_model
from app.tools import TOOLS


def build_graph() -> CompiledStateGraph:
    model = get_chat_model().bind_tools(TOOLS)

    def agent(state: MessagesState) -> dict:
        messages = [SystemMessage(content=settings.system_prompt)] + state["messages"]
        response = model.invoke(messages)
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    # 프로덕션에서는 InMemorySaver 대신 PostgresSaver/RedisSaver 등으로 교체
    return builder.compile(checkpointer=InMemorySaver())
