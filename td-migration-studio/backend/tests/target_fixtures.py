"""Self-contained Olist-like TableMeta/TablePlan fixtures for the targets workstream tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pyarrow as pa

from app.connectors.registry import get_target_meta
from app.contracts.models import ColumnMeta, ColumnPlan, PiiTag, TableMeta, TablePlan
from app.typemap import arrow_type, resolve_type, target_type_info


def col(name: str, base_type: str, ordinal: int = 0, **kw) -> ColumnMeta:
    return ColumnMeta(
        name=name,
        ordinal=ordinal,
        base_type=base_type,
        td_type=kw.pop("td_type", base_type),
        td_type_code="x",
        **kw,
    )


def table(name: str, columns: list[ColumnMeta], **kw) -> TableMeta:
    cols = [c.model_copy(update={"ordinal": i + 1}) for i, c in enumerate(columns)]
    return TableMeta(database="RETAIL_DW", name=name, columns=cols, **kw)


ORDERS = table(
    "ORDERS",
    [
        col("order_id", "CHAR", length=32, charset="LATIN", nullable=False),
        col("customer_id", "CHAR", length=32, charset="LATIN", nullable=False),
        col("order_status", "VARCHAR", length=20, charset="LATIN"),
        col("order_purchase_timestamp", "TIMESTAMP", fractional_seconds=0, nullable=False),
        col("order_delivered_customer_date", "TIMESTAMP", fractional_seconds=0),
    ],
    primary_index=["order_id"],
    primary_index_unique=True,
    partition_expression="RANGE_N(CAST(order_purchase_timestamp AS DATE) BETWEEN DATE '2016-01-01' "
    "AND DATE '2018-12-31' EACH INTERVAL '1' MONTH)",
    partition_columns=["order_purchase_timestamp"],
)

ORDER_REVIEWS = table(
    "ORDER_REVIEWS",
    [
        col("review_id", "CHAR", length=32, charset="LATIN", nullable=False),
        col("order_id", "CHAR", length=32, charset="LATIN", nullable=False),
        col("review_score", "BYTEINT"),
        col("review_comment_message", "VARCHAR", length=5000, charset="UNICODE"),
        col("review_answer_timestamp", "TIMESTAMP_TZ", fractional_seconds=0),
    ],
    primary_index=["review_id"],
    unique_keys=[["review_id", "order_id"]],
)

GEOLOCATION = table(
    "GEOLOCATION",
    [
        col("geolocation_zip_code_prefix", "CHAR", length=5, charset="LATIN", nullable=False),
        col("geolocation_lat", "NUMBER"),
        col("geolocation_lng", "NUMBER"),
        col("geolocation_city", "VARCHAR", length=60, charset="UNICODE"),
    ],
    primary_index=["geolocation_zip_code_prefix"],
)

# One column of (nearly) every loadable type, for load/profile/checksum round trips.
MIXED = table(
    "MIXED",
    [
        col("id", "INTEGER", nullable=False),
        col("score", "BYTEINT"),
        col("amount", "DECIMAL", precision=10, scale=2),
        col("lat", "NUMBER"),
        col("ratio", "FLOAT"),
        col("name", "VARCHAR", length=50, charset="UNICODE"),
        col("code", "CHAR", length=5, charset="LATIN"),
        col("d", "DATE"),
        col("ts", "TIMESTAMP", fractional_seconds=6),
        col("ts_tz", "TIMESTAMP_TZ", fractional_seconds=6),
        col("payload", "VARBYTE", length=16),
    ],
    primary_index=["id"],
    primary_index_unique=True,
)


def plan(
    target_id: str,
    meta_table: TableMeta,
    options: dict | None = None,
    container: str = "retail_dw",
    pii: dict[str, str] | None = None,
) -> TablePlan:
    meta = get_target_meta(target_id)
    cols = [
        ColumnPlan(
            source=c,
            target_name=c.name.lower(),
            mapping=resolve_type(meta, c),
            pii=PiiTag(category="identifier", confidence=0.9, reason="test", masking=pii[c.name])
            if pii and c.name in pii
            else None,
        )
        for c in meta_table.columns
    ]
    return TablePlan(
        source=meta_table,
        target_container=container,
        target_table=meta_table.name.lower(),
        columns=cols,
        target_options=options or {},
    )


def mixed_rows(n: int, offset: int = 0) -> dict[str, list]:
    rows: dict[str, list] = {c.name: [] for c in MIXED.columns}
    for i in range(offset, offset + n):
        none = i % 7 == 3
        rows["id"].append(i)
        rows["score"].append(None if none else (i % 256) - 128)
        rows["amount"].append(None if none else Decimal(i * 37 % 100000) / 100)
        rows["lat"].append(None if none else Decimal("-23.545621") + Decimal(i) / 1000)
        rows["ratio"].append(None if none else i / 3)
        rows["name"].append(None if none else f"São Paulo #{i}")
        rows["code"].append(f"{i % 99999:05d}")
        rows["d"].append(date(2017, 1 + i % 12, 1 + i % 28))
        rows["ts"].append(datetime(2018, 1 + i % 12, 1 + i % 28, i % 24, i % 60, i % 60, i * 7 % 1000000))
        rows["ts_tz"].append(None if none else datetime(2018, 5, 1, i % 24, 0, 0, tzinfo=timezone.utc))
        rows["payload"].append(None if none else bytes([i % 256, (i * 3) % 256]))
    return rows


def write_parquet(path, target_id: str, target_plan: TablePlan, rows: dict[str, list]) -> pa.Schema:
    """Stage like the pipeline would: Parquet with source column names and target Arrow types."""
    import pyarrow.parquet as pq

    meta = get_target_meta(target_id)
    schema = pa.schema(
        [
            pa.field(c.source.name, arrow_type(target_type_info(meta, c.effective_type).arrow_type))
            for c in target_plan.columns
        ]
    )
    pq.write_table(pa.table({f.name: rows[f.name] for f in schema}, schema=schema), path)
    return schema
