from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "provider:model-id" 형식 (예: "anthropic:claude-opus-5-5").
    # 비어 있으면 echo 스텁 모델로 동작한다.
    llm_model: str = ""

    system_prompt: str = (
        "당신은 친절한 AI 어시스턴트입니다. "
        "필요하면 제공된 도구를 사용해 정확하게 답하세요. "
        "한국어 질문에는 한국어로 답합니다."
    )

    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
