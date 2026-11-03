"""LangGraph 에이전트가 사용할 도구 모음.

모델 선정과 무관하게 동작하는 예시 도구들. 실제 서비스 도구로 교체/추가한다.
"""

import ast
import json
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from app.db import get_catalog_doc, get_table_details_doc, run_select

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("지원하지 않는 수식입니다.")


@tool
def get_current_time(timezone: str = "Asia/Seoul") -> str:
    """현재 날짜와 시간을 조회한다. timezone은 IANA 형식 (예: 'Asia/Seoul', 'UTC')."""
    now = datetime.now(ZoneInfo(timezone))
    return now.strftime(f"%Y-%m-%d %H:%M:%S ({timezone})")


@tool
def calculate(expression: str) -> str:
    """사칙연산 수식을 계산한다. 예: '12 * (3 + 4)'"""
    try:
        result = _safe_eval(ast.parse(expression, mode="eval"))
        return f"{expression} = {result}"
    except Exception:
        return f"계산할 수 없는 수식입니다: {expression}"


@tool
def list_tables() -> str:
    """분석 DB의 테이블 카탈로그(테이블별 한 줄 설명)와 조인 관계 지도를 조회한다.

    데이터 질문을 받으면 가장 먼저 호출해, 답변에 필요한 테이블들을 고를 것.
    """
    return get_catalog_doc()


@tool
def get_table_details(tables: list[str]) -> str:
    """지정한 테이블들의 컬럼 상세(타입·의미 설명)를 조회한다.

    list_tables 로 고른, SQL 에 사용할 테이블만 요청할 것. 예: ["orders", "customers"]
    """
    return get_table_details_doc(tables)


@tool
def run_sql(query: str) -> str:
    """분석 DB에서 SELECT 쿼리를 실행한다 (DuckDB SQL, 읽기 전용, 최대 50행).

    결과는 {"columns": [...], "rows": [[...]], "truncated": bool} JSON 문자열.
    집계·조인·정렬은 SQL 로 수행하고, 원본 전체를 가져오지 말 것.
    """
    try:
        result = run_select(query)
    except Exception as e:
        return f"SQL 실행 실패: {e}"
    return json.dumps(result, ensure_ascii=False)


TOOLS = [get_current_time, calculate, list_tables, get_table_details, run_sql]
