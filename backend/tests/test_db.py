import pytest

from app.db import get_conn, run_select


def test_migrations_applied():
    conn = get_conn()
    versions = {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()}
    assert {"V1", "V2"} <= versions


def test_join_query():
    result = run_select(
        """
        SELECT c.name, SUM(o.amount) AS total
        FROM orders o JOIN customers c ON o.customer_id = c.id
        GROUP BY c.name ORDER BY total DESC
        """
    )
    assert result["columns"] == ["name", "total"]
    assert len(result["rows"]) == 8  # 고객 8명 전원 주문 보유
    totals = [r[1] for r in result["rows"]]
    assert totals == sorted(totals, reverse=True)


def test_cte_query_allowed():
    result = run_select(
        """
        WITH top_products AS (
            SELECT product_id, SUM(amount) AS total
            FROM orders GROUP BY product_id
        )
        SELECT p.name, t.total FROM top_products t
        JOIN products p ON p.id = t.product_id
        ORDER BY t.total DESC LIMIT 3
        """
    )
    assert len(result["rows"]) == 3


def test_row_limit_enforced():
    # 내부에 LIMIT 이 없어도 최대 행수로 잘린다
    result = run_select("SELECT * FROM orders", max_rows=10)
    assert len(result["rows"]) == 10
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DROP TABLE orders",
        "INSERT INTO orders VALUES (99, 1, 1, 1, 1000, DATE '2026-11-03')",
        "UPDATE customers SET grade = 'VIP'",
        "SELECT 1; DROP TABLE orders",
        "SELECT * FROM orders; --",
    ],
)
def test_non_select_rejected(bad_sql):
    with pytest.raises(ValueError):
        run_select(bad_sql)
