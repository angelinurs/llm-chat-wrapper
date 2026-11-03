"""테스트 공통 설정.

테스트는 항상 echo 스텁 모드로 실행한다.
환경변수가 .env 보다 우선하므로, app 모듈 import 전에 LLM_MODEL 을 비워
.env 에 실제 모델이 설정되어 있어도 테스트가 API 를 호출하지 않게 한다.
"""

import os

os.environ["LLM_MODEL"] = ""
os.environ["DB_BACKEND"] = "duckdb"  # 단위 테스트는 외부 의존 없는 DuckDB 로 고정
