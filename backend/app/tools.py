"""LangGraph 에이전트가 사용할 도구 모음.

모델 선정과 무관하게 동작하는 예시 도구들. 실제 서비스 도구로 교체/추가한다.
"""

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

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


TOOLS = [get_current_time, calculate]
