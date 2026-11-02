from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CommonResponse(BaseModel, Generic[T]):
    """모든 API 응답의 공통 envelope."""

    success: bool = True
    code: str = "OK"
    message: str = ""
    data: T | None = None

    @classmethod
    def ok(cls, data: T) -> "CommonResponse[T]":
        return cls(data=data)


class HealthData(BaseModel):
    status: str
    llm_model: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="대화 세션 ID (멀티턴 thread_id)")
    message: str = Field(..., min_length=1, description="사용자 메시지")


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tools_used: list[str] = []


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]
