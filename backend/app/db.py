"""분석 DB 액세스 계층 — DB_BACKEND 환경변수로 구현을 전환한다.

- duckdb (기본): in-memory + Flyway 식 마이그레이션. dev/테스트용 Oracle 대역.
- oracle: 읽기 전용 Oracle 접속(프로덕션). 접속 정보는 환경변수(k8s Secret 등)로
  주입받고, 스키마 카탈로그는 데이터 딕셔너리에서 생성한다.

공개 인터페이스(get_catalog_doc / get_table_details_doc / run_select)가 동일하므로
tools·graph·frontend 는 어떤 백엔드가 꽂혀 있는지 모른다.
"""

import logging
import re
import threading
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("app")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MAX_ROWS = 50  # LLM/화면에 전달할 최대 행수

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|attach|detach|copy|"
    r"pragma|export|import|call|set|install|load|begin|commit|grant|revoke|merge)\b",
    re.IGNORECASE,
)


def _validate_select(sql: str) -> str:
    """SELECT 단일문만 통과시키는 공통 검증 (백엔드 무관)."""
    stmt = sql.strip().rstrip(";").strip()
    if ";" in stmt:
        raise ValueError("단일 SELECT 문만 실행할 수 있습니다.")
    if not re.match(r"(?is)^(select|with)\b", stmt):
        raise ValueError("SELECT(또는 WITH ... SELECT) 문만 실행할 수 있습니다.")
    if _FORBIDDEN.search(stmt):
        raise ValueError("읽기 전용 DB 입니다. 조회(SELECT) 외 구문은 허용되지 않습니다.")
    return stmt


def _normalize_result(columns: list[str], raw: list, max_rows: int) -> dict[str, Any]:
    truncated = len(raw) > max_rows
    rows = [
        [v if isinstance(v, (int, float, str, bool)) or v is None else str(v) for v in r]
        for r in raw[:max_rows]
    ]
    return {"columns": columns, "rows": rows, "truncated": truncated}


# ── DuckDB 백엔드 (dev/테스트) ─────────────────────────────────


class DuckDBBackend:
    DIALECT = "DuckDB SQL"

    TABLE_CATALOG: dict[str, str] = {
        "customers": "고객 마스터 (이름, 등급 VIP/GOLD/SILVER, 거주 도시, 가입일)",
        "products": "상품 마스터 (상품명, 카테고리 전자/식품/의류, 단가)",
        "orders": "주문 내역 (고객·상품별 수량, 결제 금액, 주문일)",
    }

    RELATION_MAP = """\
orders.customer_id → customers.id  (고객 1 : N 주문)
orders.product_id  → products.id   (상품 1 : N 주문)"""

    TABLE_DETAILS: dict[str, str] = {
        "customers": """\
테이블: customers (고객)
  - id INTEGER PK
  - name VARCHAR          : 고객 이름
  - grade VARCHAR         : 등급 ('VIP' | 'GOLD' | 'SILVER')
  - city VARCHAR          : 거주 도시
  - created_at DATE       : 가입일""",
        "products": """\
테이블: products (상품)
  - id INTEGER PK
  - name VARCHAR          : 상품명
  - category VARCHAR      : 카테고리 ('전자' | '식품' | '의류')
  - price INTEGER         : 단가(원)""",
        "orders": """\
테이블: orders (주문)
  - id INTEGER PK
  - customer_id INTEGER   : FK → customers.id
  - product_id INTEGER    : FK → products.id
  - quantity INTEGER      : 수량
  - amount INTEGER        : 결제 금액(원) = 단가 * 수량
  - order_date DATE       : 주문일""",
    }

    def __init__(self) -> None:
        self._conn = None
        self._lock = threading.Lock()

    def connect(self):
        import duckdb

        with self._lock:
            if self._conn is None:
                self._conn = duckdb.connect(":memory:")
                self._run_migrations(self._conn)
            return self._conn

    def _run_migrations(self, conn) -> None:
        """Flyway 스타일: V*.sql 을 이름순으로, 미적용분만 실행."""
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version VARCHAR PRIMARY KEY)"
        )
        applied = {
            r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
        }
        for path in sorted(MIGRATIONS_DIR.glob("V*.sql")):
            version = path.name.split("__")[0]
            if version in applied:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_version VALUES (?)", [version])
            logger.info("migration 적용: %s", path.name)

    def catalog_doc(self) -> str:
        lines = [f"[테이블 카탈로그 — {self.DIALECT} 사용]"]
        lines += [f"- {name} : {desc}" for name, desc in self.TABLE_CATALOG.items()]
        lines += ["", "[관계 지도]", self.RELATION_MAP]
        return "\n".join(lines)

    def table_details_doc(self, tables: list[str]) -> str:
        known = [t for t in tables if t in self.TABLE_DETAILS]
        unknown = [t for t in tables if t not in self.TABLE_DETAILS]
        parts = [self.TABLE_DETAILS[t] for t in known]
        if unknown:
            parts.append(
                f"(존재하지 않는 테이블: {', '.join(unknown)} — "
                f"사용 가능한 테이블: {', '.join(self.TABLE_DETAILS)})"
            )
        return "\n\n".join(parts) if parts else "요청된 테이블이 없습니다."

    def run_select(self, sql: str, max_rows: int = MAX_ROWS) -> dict[str, Any]:
        stmt = _validate_select(sql)
        cur = self.connect().cursor()  # 스레드 안전: 쿼리마다 cursor
        try:
            # 바깥에서 감싸 행수를 강제 제한 (내부 LIMIT 유무와 무관)
            cur.execute(f"SELECT * FROM ({stmt}) AS _t LIMIT {max_rows + 1}")
            columns = [d[0] for d in cur.description]
            raw = cur.fetchall()
        finally:
            cur.close()
        return _normalize_result(columns, raw, max_rows)


# ── Oracle 백엔드 (프로덕션) ───────────────────────────────────


class OracleBackend:
    """읽기 전용 Oracle. 카탈로그·상세는 데이터 딕셔너리에서 생성한다.

    DBA 가 COMMENT ON TABLE/COLUMN 을 충실히 달아둘수록
    text-to-SQL 품질이 올라간다. 접속 계정은 SELECT 전용 권한을 권장.
    """

    DIALECT = "Oracle SQL"

    def __init__(self) -> None:
        if not (settings.oracle_dsn and settings.oracle_user and settings.oracle_password):
            raise RuntimeError(
                "DB_BACKEND=oracle 에는 ORACLE_DSN / ORACLE_USER / ORACLE_PASSWORD "
                "환경변수가 필요합니다."
            )
        try:
            import oracledb
        except ImportError as e:
            raise RuntimeError(
                "oracledb 패키지가 설치되어 있지 않습니다: uv sync --extra oracle"
            ) from e
        self._pool = oracledb.create_pool(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=settings.oracle_dsn,
            min=1,
            max=4,
        )

    @property
    def _owner(self) -> str:
        return (settings.oracle_schema or settings.oracle_user).upper()

    def catalog_doc(self) -> str:
        tables_sql = """
            SELECT t.table_name, NVL(c.comments, '(설명 없음)')
            FROM all_tables t
            LEFT JOIN all_tab_comments c
              ON c.owner = t.owner AND c.table_name = t.table_name
            WHERE t.owner = :owner
            ORDER BY t.table_name
        """
        fks_sql = """
            SELECT a.table_name, ac.column_name, r.table_name, rc.column_name
            FROM all_constraints a
            JOIN all_cons_columns ac
              ON ac.owner = a.owner AND ac.constraint_name = a.constraint_name
            JOIN all_constraints r
              ON r.owner = a.r_owner AND r.constraint_name = a.r_constraint_name
            JOIN all_cons_columns rc
              ON rc.owner = r.owner AND rc.constraint_name = r.constraint_name
             AND rc.position = ac.position
            WHERE a.constraint_type = 'R' AND a.owner = :owner
            ORDER BY a.table_name
        """
        with self._pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(tables_sql, owner=self._owner)
                tables = cur.fetchall()
                cur.execute(fks_sql, owner=self._owner)
                fks = cur.fetchall()

        lines = [f"[테이블 카탈로그 — {self.DIALECT} 사용]"]
        lines += [f"- {name.lower()} : {comment}" for name, comment in tables]
        lines += ["", "[관계 지도]"]
        lines += [
            f"{t.lower()}.{c.lower()} → {rt.lower()}.{rc.lower()}"
            for t, c, rt, rc in fks
        ] or ["(FK 제약 없음)"]
        return "\n".join(lines)

    def table_details_doc(self, tables: list[str]) -> str:
        cols_sql = """
            SELECT c.column_name, c.data_type, NVL(cc.comments, '')
            FROM all_tab_columns c
            LEFT JOIN all_col_comments cc
              ON cc.owner = c.owner AND cc.table_name = c.table_name
             AND cc.column_name = c.column_name
            WHERE c.owner = :owner AND c.table_name = :tname
            ORDER BY c.column_id
        """
        parts: list[str] = []
        with self._pool.acquire() as conn:
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(cols_sql, owner=self._owner, tname=table.upper())
                    cols = cur.fetchall()
                    if not cols:
                        parts.append(f"(존재하지 않는 테이블: {table})")
                        continue
                    body = "\n".join(
                        f"  - {name.lower()} {dtype}" + (f" : {comment}" if comment else "")
                        for name, dtype, comment in cols
                    )
                    parts.append(f"테이블: {table.lower()}\n{body}")
        return "\n\n".join(parts) if parts else "요청된 테이블이 없습니다."

    def run_select(self, sql: str, max_rows: int = MAX_ROWS) -> dict[str, Any]:
        stmt = _validate_select(sql)
        # Oracle 은 인라인 뷰 안의 WITH 를 허용하지 않는 버전이 있어 분기
        if re.match(r"(?is)^with\b", stmt):
            wrapped = f"{stmt} FETCH FIRST {max_rows + 1} ROWS ONLY"
        else:
            wrapped = f"SELECT * FROM ({stmt}) _t FETCH FIRST {max_rows + 1} ROWS ONLY"
        with self._pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(wrapped)
                columns = [d[0].lower() for d in cur.description]
                raw = cur.fetchall()
        return _normalize_result(columns, raw, max_rows)


# ── 백엔드 선택 + 공개 인터페이스 ──────────────────────────────

_backend: Any = None
_backend_lock = threading.Lock()


def get_backend():
    """DB_BACKEND 설정값에 따라 구현을 선택한다 (최초 1회 생성 후 재사용)."""
    global _backend
    with _backend_lock:
        if _backend is None:
            kind = settings.db_backend.lower()
            if kind == "duckdb":
                _backend = DuckDBBackend()
            elif kind == "oracle":
                _backend = OracleBackend()
            else:
                raise ValueError(
                    f"지원하지 않는 DB_BACKEND: {kind!r} (duckdb | oracle)"
                )
            logger.info("분석 DB 백엔드: %s", kind)
        return _backend


def init_db():
    """서버 기동 시 호출. DuckDB 는 이 시점에 마이그레이션까지 적용한다."""
    backend = get_backend()
    if isinstance(backend, DuckDBBackend):
        backend.connect()
    return backend


def get_catalog_doc() -> str:
    return get_backend().catalog_doc()


def get_table_details_doc(tables: list[str]) -> str:
    return get_backend().table_details_doc(tables)


def run_select(sql: str, max_rows: int = MAX_ROWS) -> dict[str, Any]:
    return get_backend().run_select(sql, max_rows)


def get_conn():
    """DuckDB 전용 하위 호환 (테스트에서 사용)."""
    backend = get_backend()
    if not isinstance(backend, DuckDBBackend):
        raise RuntimeError("get_conn() 은 duckdb 백엔드에서만 사용할 수 있습니다.")
    return backend.connect()
