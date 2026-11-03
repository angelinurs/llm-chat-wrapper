"""분석용 DuckDB (dev 환경의 Oracle 대역).

- Flyway 스타일 마이그레이션: migrations/V*.sql 을 이름순으로 적용하고
  schema_version 테이블에 적용 이력을 기록한다.
- run_select: SELECT 단일문만 허용 + 결과 행수 강제 제한 (읽기 전용 보장).
- 프로덕션(Oracle) 전환 시 이 모듈의 커넥션/방언만 교체하면 된다.
"""

import logging
import re
import threading
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("app")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MAX_ROWS = 50  # LLM/화면에 전달할 최대 행수

# LLM 에게 제공하는 스키마 상세 설명 (프로덕션에서는 Oracle 딕셔너리/COMMENT 로 대체)
SCHEMA_DOC = """\
[분석 DB 스키마 — DuckDB SQL 사용]

테이블: customers (고객)
  - id INTEGER PK
  - name VARCHAR          : 고객 이름
  - grade VARCHAR         : 등급 ('VIP' | 'GOLD' | 'SILVER')
  - city VARCHAR          : 거주 도시
  - created_at DATE       : 가입일

테이블: products (상품)
  - id INTEGER PK
  - name VARCHAR          : 상품명
  - category VARCHAR      : 카테고리 ('전자' | '식품' | '의류')
  - price INTEGER         : 단가(원)

테이블: orders (주문)
  - id INTEGER PK
  - customer_id INTEGER   : FK → customers.id
  - product_id INTEGER    : FK → products.id
  - quantity INTEGER      : 수량
  - amount INTEGER        : 결제 금액(원)
  - order_date DATE       : 주문일

관계:
  orders.customer_id → customers.id  (고객 1 : N 주문)
  orders.product_id  → products.id   (상품 1 : N 주문)
"""

_conn: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|attach|detach|copy|"
    r"pragma|export|import|call|set|install|load|begin|commit)\b",
    re.IGNORECASE,
)


def init_db() -> duckdb.DuckDBPyConnection:
    """in-memory DB 생성 + 마이그레이션 적용 (멱등)."""
    global _conn
    with _lock:
        if _conn is None:
            _conn = duckdb.connect(":memory:")
            _run_migrations(_conn)
        return _conn


def get_conn() -> duckdb.DuckDBPyConnection:
    return init_db()


def _run_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version VARCHAR PRIMARY KEY)"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()}
    for path in sorted(MIGRATIONS_DIR.glob("V*.sql")):
        version = path.name.split("__")[0]
        if version in applied:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_version VALUES (?)", [version])
        logger.info("migration 적용: %s", path.name)


def get_schema_doc() -> str:
    return SCHEMA_DOC


def run_select(sql: str, max_rows: int = MAX_ROWS) -> dict[str, Any]:
    """검증된 SELECT 를 실행하고 {columns, rows, truncated} 를 반환한다."""
    stmt = sql.strip().rstrip(";").strip()
    if ";" in stmt:
        raise ValueError("단일 SELECT 문만 실행할 수 있습니다.")
    if not re.match(r"(?is)^(select|with)\b", stmt):
        raise ValueError("SELECT(또는 WITH ... SELECT) 문만 실행할 수 있습니다.")
    if _FORBIDDEN.search(stmt):
        raise ValueError("읽기 전용 DB 입니다. 조회(SELECT) 외 구문은 허용되지 않습니다.")

    cur = get_conn().cursor()  # 스레드 안전을 위해 쿼리마다 cursor 사용
    try:
        # 바깥에서 한 번 더 감싸 행수를 강제 제한 (내부 LIMIT 유무와 무관)
        cur.execute(f"SELECT * FROM ({stmt}) AS _t LIMIT {max_rows + 1}")
        columns = [d[0] for d in cur.description]
        raw = cur.fetchall()
    finally:
        cur.close()

    truncated = len(raw) > max_rows
    rows = [
        [v if isinstance(v, (int, float, str, bool)) or v is None else str(v) for v in r]
        for r in raw[:max_rows]
    ]
    return {"columns": columns, "rows": rows, "truncated": truncated}
