"""Integration: seed the emulated Teradata into the docker-compose Postgres and read it back."""

import os
from pathlib import Path

import psycopg
import pyarrow as pa
import pytest

from app.connectors.source.emulated import EmulatedTeradataSource
from app.connectors.source.seed import seed
from app.contracts.models import ProfileSpec
from app.contracts.models import TdBaseType as T
from app.settings import Settings

pytestmark = pytest.mark.integration
DSN = os.environ.get("TD_EMU_DSN", "postgresql://studio:studio@localhost:5432/tdemu")
ROOT = Path(__file__).resolve().parents[2]
# Counts are CSV *records*. order_reviews has 104,720 physical lines because review texts contain quoted
# newlines; it holds 99,224 records (the "104719" sometimes quoted is the line count minus header).
EXPECTED_ROWS = {
    "CUSTOMERS": 99441, "ORDERS": 99441, "ORDER_ITEMS": 112650, "ORDER_PAYMENTS": 103886,
    "ORDER_REVIEWS": 99224, "PRODUCTS": 32951, "SELLERS": 3095, "PRODUCT_CATEGORY_TRANSLATION": 71,
    "GEOLOCATION": 1000163,
}  # fmt: skip


@pytest.fixture(scope="module")
def src():
    try:
        psycopg.connect(DSN, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable ({exc}); run `docker compose up -d postgres`")
    settings = Settings(td_emu_dsn=DSN, ddl_dir=ROOT / "source/ddl/teradata", seed_dir=ROOT / "data/olist")
    seed(settings)
    s = EmulatedTeradataSource(settings)
    yield s
    s.close()


def test_seed_is_idempotent(src):
    again = seed(src.settings)
    assert again.skipped and again.row_counts == EXPECTED_ROWS


def test_row_counts(src):
    tables = {t.name: t for t in src.list_tables("RETAIL_DW")}
    assert {n: t.row_count for n, t in tables.items()} == EXPECTED_ROWS
    assert all(t.size_bytes > 0 for t in tables.values())
    with psycopg.connect(DSN) as conn:
        for name, n in EXPECTED_ROWS.items():
            assert conn.execute(f"SELECT COUNT(*) FROM retail_dw.{name.lower()}").fetchone()[0] == n


def test_describe_table(src):
    orders = src.describe_table("RETAIL_DW", "ORDERS")
    assert (
        orders.kind == "MULTISET" and orders.primary_index == ["order_id"] and not orders.primary_index_unique
    )
    assert orders.unique_keys == [["order_id"]]
    assert orders.partition_columns == ["order_purchase_timestamp"]
    assert orders.partition_expression.upper().startswith("RANGE_N(")
    assert [(f.columns, f.ref_table, f.enforced) for f in orders.foreign_keys] == [
        (["customer_id"], "CUSTOMERS", False)
    ]
    assert orders.ddl.startswith("CREATE MULTISET TABLE RETAIL_DW.ORDERS")
    cust = src.describe_table("retail_dw", "customers")
    assert cust.kind == "SET" and cust.primary_index_unique and cust.unique_keys == [["customer_id"]]
    rev = {c.name: c for c in src.columns("RETAIL_DW", "ORDER_REVIEWS")}
    assert (rev["review_score"].base_type, rev["review_score"].td_type_code) == (T.BYTEINT, "I1")
    assert rev["review_answer_timestamp"].td_type == "TIMESTAMP(0) WITH TIME ZONE"
    assert (rev["review_comment_message"].length, rev["review_comment_message"].charset) == (5000, "UNICODE")
    items = src.describe_table("RETAIL_DW", "ORDER_ITEMS")
    assert items.unique_keys == [["order_id", "order_item_id"]] and len(items.foreign_keys) == 3
    geo = {c.name: c for c in src.columns("RETAIL_DW", "GEOLOCATION")}
    assert geo["geolocation_lat"].base_type == T.NUMBER and geo["geolocation_lat"].precision is None


def test_extract_arrow_types(src):
    batches = src.extract("RETAIL_DW", "ORDER_REVIEWS", batch_rows=50_000)
    first = next(batches)
    assert first.num_rows == 50_000
    assert first.schema == pa.schema([
        pa.field("review_id", pa.string(), nullable=False), pa.field("order_id", pa.string(), nullable=False),
        pa.field("review_score", pa.int8(), nullable=False), pa.field("review_comment_title", pa.string()),
        pa.field("review_comment_message", pa.string()), pa.field("review_creation_date", pa.timestamp("us")),
        pa.field("review_answer_timestamp", pa.timestamp("us", tz="UTC")),
    ])  # fmt: skip
    assert sum(b.num_rows for b in batches) + first.num_rows == EXPECTED_ROWS["ORDER_REVIEWS"]
    # 2018-01-18 21:46:59 at -03:00 in the CSV
    row = first.slice(0, 1).to_pylist()[0]
    assert row["review_id"] == "7bc2406110b926393aa56f80a40eba40"
    assert row["review_answer_timestamp"].isoformat() == "2018-01-19T00:46:59+00:00"

    (cust,) = list(src.extract("RETAIL_DW", "SELLERS", columns=["seller_state", "seller_id"]))
    assert cust.schema.names == ["seller_state", "seller_id"] and cust.num_rows == 3095
    assert all(len(v) == 2 for v in cust.column("seller_state").to_pylist() if v)  # CHAR right-trimmed

    items = next(src.extract("RETAIL_DW", "ORDER_ITEMS", batch_rows=10))
    assert items.schema.field("price").type == pa.decimal128(10, 2)
    assert items.schema.field("order_item_id").type == pa.int16()
    geo = next(src.extract("RETAIL_DW", "GEOLOCATION", batch_rows=10))
    assert geo.schema.field("geolocation_lat").type == pa.decimal128(38, 15)
    prod = next(src.extract("RETAIL_DW", "PRODUCTS", batch_rows=10))
    assert prod.schema.field("product_photos_qty").type == pa.int8()
    assert prod.schema.field("product_weight_g").type == pa.int32()
    orders = next(src.extract("RETAIL_DW", "ORDERS", batch_rows=10))
    assert orders.schema.field("order_estimated_delivery_date").type == pa.date32()


def test_profile(src):
    spec = ProfileSpec(
        numeric_columns=["price", "order_item_id"],
        null_columns=["freight_value"],
        checksum_columns=["order_id", "price"],
        unique_keys=[["order_id", "order_item_id"], ["order_id"]],
    )
    p = src.profile("RETAIL_DW", "ORDER_ITEMS", spec)
    assert p.row_count == 112650
    cols = {c.column: c for c in p.columns}
    assert (cols["price"].sum, cols["price"].min, cols["price"].max) == ("13591643.70", "0.85", "6735.00")
    assert cols["order_item_id"].min == "1" and cols["freight_value"].null_count == 0
    assert p.duplicate_key_count["order_id,order_item_id"] == 0
    assert p.duplicate_key_count["order_id"] > 0
    assert p.checksum


def test_test_connection(src):
    res = src.test_connection()
    assert res.ok and res.mode == "emulated" and "emulated" in res.server_version and res.latency_ms >= 0


@pytest.mark.parametrize(
    "table", ["ORDER_REVIEWS", "GEOLOCATION", "ORDER_ITEMS", "ORDERS", "PRODUCTS", "CUSTOMERS"]
)
def test_checksum_matches_duckdb_reference(src, table):
    import duckdb

    from app.contracts.checksum import duckdb_checksum_sql

    arrow = pa.Table.from_batches(list(src.extract("RETAIL_DW", table, batch_rows=500_000)))  # noqa: F841
    cols = [c.name for c in src.columns("RETAIL_DW", table)]
    ref = duckdb.sql(duckdb_checksum_sql("arrow", arrow.schema, cols)).fetchone()
    p = src.profile("RETAIL_DW", table, ProfileSpec(checksum_columns=cols))
    assert (p.row_count, p.checksum) == (ref[0], ref[1])
