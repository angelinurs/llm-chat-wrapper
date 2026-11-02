"""채팅 모델 팩토리.

LLM_MODEL 환경변수("provider:model-id")로 모델을 교체한다.
모델 미선정 상태에서는 EchoChatModel 스텁으로 전체 파이프라인을 확인할 수 있다.
"""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import settings


class EchoChatModel(BaseChatModel):
    """모델 미설정 시 사용하는 스텁. 마지막 사용자 입력을 그대로 되돌려준다."""

    @property
    def _llm_type(self) -> str:
        return "echo-stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = next(
            (m.content for m in reversed(messages) if m.type == "human"), ""
        )
        text = (
            "[echo 모드] 아직 LLM 모델이 설정되지 않았습니다. "
            f"LLM_MODEL 환경변수를 설정하세요. 입력하신 내용: {last_human}"
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=text))]
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> "EchoChatModel":
        # 스텁은 tool call을 생성하지 않으므로 바인딩을 무시한다.
        return self


def get_chat_model() -> BaseChatModel:
    if settings.llm_model:
        return init_chat_model(settings.llm_model)
    return EchoChatModel()
