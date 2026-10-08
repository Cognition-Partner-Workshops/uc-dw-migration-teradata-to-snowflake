from pathlib import Path

import pytest

from app.connectors.source.td_ddl import DDLParseError, parse_ddl, parse_table
from app.contracts.models import TdBaseType as T

DDL_DIR = Path(__file__).resolve().parents[2] / "source" / "ddl" / "teradata"

# name: (file, kind, PI, PI unique, unique_keys, partition_columns, FK (cols, parent) pairs, n columns)
EXPECTED = {
    "CUSTOMERS": ("01_customers.sql", "SET", ["customer_id"], True, [["customer_id"]], [], [], 5),
    "SELLERS": ("02_sellers.sql", "SET", ["seller_id"], True, [["seller_id"]], [], [], 4),
    "PRODUCT_CATEGORY_TRANSLATION": (
        "03_product_category_translation.sql", "SET", ["product_category_name"], True,
        [["product_category_name"]], [], [], 2,
    ),
    "PRODUCTS": (
        "04_products.sql", "SET", ["product_id"], True, [["product_id"]], [],
        [(["product_category_name"], "PRODUCT_CATEGORY_TRANSLATION")], 9,
    ),
    "ORDERS": (
        "05_orders.sql", "MULTISET", ["order_id"], False, [["order_id"]], ["order_purchase_timestamp"],
        [(["customer_id"], "CUSTOMERS")], 8,
    ),
    "ORDER_ITEMS": (
        "06_order_items.sql", "MULTISET", ["order_id"], False, [["order_id", "order_item_id"]], [],
        [(["order_id"], "ORDERS"), (["product_id"], "PRODUCTS"), (["seller_id"], "SELLERS")], 7,
    ),
    "ORDER_PAYMENTS": (
        "07_order_payments.sql", "MULTISET", ["order_id"], False, [["order_id", "payment_sequential"]], [],
        [(["order_id"], "ORDERS")], 5,
    ),
    "ORDER_REVIEWS": (
        "08_order_reviews.sql", "MULTISET", ["review_id"], False, [["review_id", "order_id"]], [],
        [(["order_id"], "ORDERS")], 7,
    ),
    "GEOLOCATION": ("09_geolocation.sql", "MULTISET", ["geolocation_zip_code_prefix"], False, [], [], [], 5),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_parse_olist_tables(name):
    file, kind, pi, pi_unique, uks, parts, fks, ncols = EXPECTED[name]
    text = (DDL_DIR / file).read_text()
    m = parse_table(text, "RETAIL_DW").meta
    assert (m.database, m.name, m.kind) == ("RETAIL_DW", name, kind)
    assert (m.primary_index, m.primary_index_unique) == (pi, pi_unique)
    assert m.unique_keys == uks
    assert m.partition_columns == parts
    assert [(f.columns, f.ref_table) for f in m.foreign_keys] == fks
    assert all(
        not f.enforced and f.ref_database == "RETAIL_DW" and f.ref_columns == f.columns
        for f in m.foreign_keys
    )
    assert len(m.columns) == ncols and [c.ordinal for c in m.columns] == list(range(1, ncols + 1))
    assert m.ddl and m.ddl.strip().upper().startswith("CREATE")


def _cols(file):
    return {c.name: c for c in parse_table((DDL_DIR / file).read_text()).meta.columns}


def test_column_types_from_olist_ddl():
    rev = _cols("08_order_reviews.sql")
    assert (rev["review_id"].base_type, rev["review_id"].length, rev["review_id"].charset) == (
        T.CHAR,
        32,
        "LATIN",
    )
    assert rev["review_id"].td_type_code == "CF" and rev["review_id"].case_specific is False
    assert not rev["review_id"].nullable and rev["review_comment_title"].nullable
    assert rev["review_score"].base_type == T.BYTEINT and rev["review_score"].td_type_code == "I1"
    assert (rev["review_comment_message"].base_type, rev["review_comment_message"].length) == (
        T.VARCHAR,
        5000,
    )
    assert rev["review_comment_message"].charset == "UNICODE"
    ts = rev["review_answer_timestamp"]
    assert (ts.base_type, ts.fractional_seconds, ts.td_type_code) == (T.TIMESTAMP_TZ, 0, "SZ")
    assert ts.td_type == "TIMESTAMP(0) WITH TIME ZONE"

    items = _cols("06_order_items.sql")
    assert (items["price"].base_type, items["price"].precision, items["price"].scale) == (T.DECIMAL, 10, 2)
    assert items["order_item_id"].td_type_code == "I2"

    geo = _cols("09_geolocation.sql")
    assert geo["geolocation_lat"].base_type == T.NUMBER and geo["geolocation_lat"].precision is None
    assert geo["geolocation_lat"].td_type_code == "N"

    orders = _cols("05_orders.sql")
    assert orders["order_status"].compress_values == [
        "delivered", "shipped", "canceled", "invoiced", "processing", "unavailable", "approved", "created",
    ]  # fmt: skip
    est = orders["order_estimated_delivery_date"]
    assert (est.base_type, est.td_type_code, est.format) == (T.DATE, "DA", "YYYY-MM-DD")


def test_orders_partitioning_and_indexes():
    pt = parse_table((DDL_DIR / "05_orders.sql").read_text())
    assert pt.meta.partition_expression.upper().startswith("RANGE_N(CAST(ORDER_PURCHASE_TIMESTAMP AS DATE)")
    assert [(i.kind, i.name, i.unique, i.columns) for i in pt.indexes] == [
        ("Q", "PI_ORDERS", False, ["order_id"]),
        ("S", "USI_ORDERS", True, ["order_id"]),
    ]


SYNTHETIC = '''
/* block comment */ -- line comment
CREATE MULTISET TABLE db1.t_all, FALLBACK, NO BEFORE JOURNAL (
  a BYTEINT NOT NULL,
  b BIGINT DEFAULT 0,
  c NUMBER(18,4),
  d DECIMAL(5) COMPRESS (0, 1),
  e FLOAT,
  f CHAR(10) CHARACTER SET UNICODE CASESPECIFIC NOT NULL,
  g VARCHAR(30) UPPERCASE COMPRESS,
  h TIMESTAMP(6) WITH TIME ZONE,
  i TIME(3),
  j DATE FORMAT 'YY/MM/DD' COMPRESS (DATE '2020-01-01'),
  k VARBYTE(100),
  l INTERVAL DAY(2) TO SECOND(6),
  m CLOB(1M) CHARACTER SET LATIN,
  "Quoted ""Col""" INTEGER,
  CONSTRAINT fk_x FOREIGN KEY (a) REFERENCES WITH NO CHECK OPTION db1.parent (pa)
)
UNIQUE PRIMARY INDEX (a, f)
PARTITION BY (RANGE_N(j BETWEEN DATE '2020-01-01' AND DATE '2020-12-31' EACH INTERVAL '1' DAY),
             CASE_N(a < 0, NO CASE))
INDEX ix_b (b);
COMMENT ON TABLE db1.t_all IS 'all types';
COMMENT ON COLUMN db1.t_all.a IS 'tiny';
'''


def test_synthetic_feature_coverage():
    (pt,) = parse_ddl(SYNTHETIC)
    m = pt.meta
    c = {x.name: x for x in m.columns}
    assert (m.database, m.name, m.kind) == ("db1", "t_all", "MULTISET")
    assert [c[n].td_type_code for n in "abcdefghijklm"] == [
        "I1", "I8", "N", "D", "F", "CF", "CV", "SZ", "AT", "DA", "BV", "DS", "CO",
    ]  # fmt: skip
    assert (c["c"].precision, c["c"].scale) == (18, 4)
    assert (c["d"].precision, c["d"].scale, c["d"].compress_values) == (5, 0, ["0", "1"])
    assert (c["f"].charset, c["f"].case_specific, c["f"].nullable) == ("UNICODE", True, False)
    assert c["g"].compress_values == [] and c["b"].default == "0"
    assert c["h"].fractional_seconds == 6 and c["i"].fractional_seconds == 3
    assert c["j"].format == "YY/MM/DD"
    assert c["k"].length == 100 and c["m"].length == 1024 * 1024
    assert (c["l"].interval_qualifier, c["l"].precision, c["l"].fractional_seconds) == ("DAY TO SECOND", 2, 6)
    assert 'Quoted "Col"' in c and c['Quoted "Col"'].base_type == T.INTEGER
    assert (m.primary_index, m.primary_index_unique) == (["a", "f"], True)
    assert m.unique_keys == [["a", "f"]]
    assert sorted(m.partition_columns) == ["a", "j"]
    assert pt.fk_names == ["fk_x"] and m.foreign_keys[0].enforced is False
    assert [(i.kind, i.unique, i.columns) for i in pt.indexes][1:] == [("S", False, ["b"])]
    assert pt.comment == "all types" and c["a"].comment == "tiny"


def test_set_table_without_explicit_pi_defaults_to_first_column():
    m = parse_table("CREATE TABLE x.y (k INTEGER, v VARCHAR(5));").meta
    assert m.kind == "SET" and m.primary_index == ["k"] and not m.primary_index_unique


def test_parse_error_is_reported():
    with pytest.raises(DDLParseError):
        parse_table("CREATE TABLE x.y (k WIBBLE);")
