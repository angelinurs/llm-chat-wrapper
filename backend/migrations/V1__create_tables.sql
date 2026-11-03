-- 고객
CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       VARCHAR NOT NULL,
    grade      VARCHAR NOT NULL,          -- VIP / GOLD / SILVER
    city       VARCHAR NOT NULL,
    created_at DATE    NOT NULL
);

-- 상품
CREATE TABLE products (
    id       INTEGER PRIMARY KEY,
    name     VARCHAR NOT NULL,
    category VARCHAR NOT NULL,            -- 전자 / 식품 / 의류
    price    INTEGER NOT NULL             -- 단가(원)
);

-- 주문 (customers, products 와 조인)
CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    product_id  INTEGER NOT NULL REFERENCES products (id),
    quantity    INTEGER NOT NULL,
    amount      INTEGER NOT NULL,         -- 결제 금액(원) = 단가 * 수량
    order_date  DATE    NOT NULL
);
