from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 를 os.environ 에도 로드한다.
# pydantic-settings 는 Settings 필드만 읽으므로, provider SDK 가 읽는
# API 키(ANTHROPIC_API_KEY 등)는 환경변수로 직접 올려줘야 한다.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "provider:model-id" 형식 (예: "anthropic:claude-opus-5-5").
    # 비어 있으면 echo 스텁 모델로 동작한다.
    llm_model: str = ""

    system_prompt: str = (
        "당신은 친절한 AI 어시스턴트입니다. "
        "필요하면 제공된 도구를 사용해 정확하게 답하세요. "
        "데이터 관련 질문에는 ① list_tables 로 카탈로그·관계 지도를 보고 필요한 테이블을 고르고, "
        "② get_table_details 로 그 테이블들의 컬럼 상세를 확인한 뒤, "
        "③ run_sql 로 SELECT 쿼리(DuckDB SQL)를 실행해 정확한 수치로 답하세요. "
        "run_sql 결과는 시스템이 이미 사용자 화면에 표로 표시합니다. "
        "따라서 답변에 마크다운 표나 행 나열을 절대 다시 쓰지 말고, "
        "핵심 수치 한두 개를 담은 요약 문장만 작성하세요. "
        "한국어 질문에는 한국어로 답합니다."
    )

    cors_origins: list[str] = ["http://localhost:3000"]

    # true 면 LangChain 디버그 로그 활성화: 매 LLM 호출의 입력 메시지 전문,
    # 응답, tool call, 소요 시간이 콘솔에 출력된다 (개발용, 출력 많음)
    llm_debug: bool = False


settings = Settings()
