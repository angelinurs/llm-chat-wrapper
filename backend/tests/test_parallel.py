import json

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Send

from app.graph import collect, route_after_agent, sql_worker


def _ai_with_parallel_call(queries: list[str], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "parallel_sql", "args": {"queries": queries}, "id": call_id}
        ],
    )


def test_route_fans_out_per_query():
    msg = _ai_with_parallel_call(["SELECT 1", "SELECT 2", "SELECT 3"])
    sends = route_after_agent({"messages": [msg], "sql_results": []})
    assert isinstance(sends, list) and len(sends) == 3
    assert all(isinstance(s, Send) and s.node == "sql_worker" for s in sends)
    assert sends[1].arg == {"index": 1, "query": "SELECT 2"}


def test_route_without_tool_calls_ends():
    assert route_after_agent({"messages": [AIMessage(content="끝")], "sql_results": []}) == END


def test_worker_and_collect_merge_results_in_order():
    q1 = "SELECT COUNT(*) AS cnt FROM orders"
    q2 = "SELECT COUNT(*) AS cnt FROM customers"
    r1 = sql_worker({"index": 0, "query": q1})
    r2 = sql_worker({"index": 1, "query": q2})

    state = {
        "messages": [_ai_with_parallel_call([q1, q2])],
        # 병렬 실행이라 도착 순서는 뒤섞일 수 있음 → 역순으로 넣어 정렬 검증
        "sql_results": r2["sql_results"] + r1["sql_results"],
    }
    out = collect(state)

    tm = out["messages"][0]
    assert tm.name == "parallel_sql" and tm.tool_call_id == "c1"
    items = json.loads(tm.content)
    assert [i["query"] for i in items] == [q1, q2]  # index 순 정렬 복원
    assert items[0]["result"]["rows"][0][0] == 35   # orders 35건
    assert items[1]["result"]["rows"][0][0] == 8    # customers 8명
    assert out["sql_results"] is None               # 다음 턴을 위해 초기화


def test_worker_captures_sql_error_without_raising():
    r = sql_worker({"index": 0, "query": "DROP TABLE orders"})
    assert "error" in r["sql_results"][0]["result"]
