"""In-memory fakes for the source/target connectors and typemap (owned by other workstreams)."""

from __future__ import annotations

import re
import shutil
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.contracts.models import (
    ColumnMeta,
    ConnectionTestResult,
    ForeignKey,
    LoadResult,
    MappingDecision,
    MigrationPlan,
    ProfileSpec,
    SourceTableSummary,
    TableMeta,
    TablePlan,
    TableProfile,
    TargetMeta,
    TargetTypeInfo,
    TdBaseType,
)
from app.contracts.source import SourceConnector
from app.contracts.target import TargetConnector
from app.pipeline.dq import profile_parquet

DB = "RETAIL_DW"
T = TdBaseType


# typemap ------------------------------------------------------------------------------------------
def fake_resolve_type(meta: TargetMeta, col: ColumnMeta) -> MappingDecision:
    b = col.base_type
    if b in (T.BYTEINT, T.SMALLINT, T.INTEGER, T.BIGINT):
        return MappingDecision(target_type="INT64")
    if b in (T.DECIMAL, T.NUMBER):
        return MappingDecision(target_type=f"NUMERIC({col.precision or 38},{col.scale or 0})")
    if b == T.FLOAT:
        return MappingDecision(target_type="FLOAT64", lossy=True, severity="info", reason="binary float")
    if b in (T.CHAR, T.VARCHAR):
        return MappingDecision(target_type=f"STRING({col.length or 255})")
    if b == T.DATE:
        return MappingDecision(target_type="DATE")
    if b == T.TIMESTAMP:
        return MappingDecision(target_type="DATETIME")
    if b == T.TIMESTAMP_TZ:
        return MappingDecision(target_type="TIMESTAMPTZ", transform="tz_to_utc")
    return MappingDecision(target_type="", severity="error", reason=f"unsupported {b}")


def fake_target_type_info(meta: TargetMeta, target_type: str) -> TargetTypeInfo:
    t = target_type.strip().upper()
    if m := re.fullmatch(r"NUMERIC\((\d+),\s*(\d+)\)", t):
        return TargetTypeInfo(target_type=t, arrow_type=f"decimal128({m[1]}, {m[2]})")
    if m := re.fullmatch(r"STRING\((\d+)\)", t):
        return TargetTypeInfo(target_type=t, arrow_type="string", max_length=int(m[1]), length_unit="chars")
    simple = {
        "INT64": "int64",
        "FLOAT64": "double",
        "STRING": "string",
        "DATE": "date32",
        "DATETIME": "timestamp[us]",
        "TIMESTAMPTZ": "timestamp[us, tz=UTC]",
    }
    if t not in simple:
        raise ValueError(f"unknown type {target_type}")
    return TargetTypeInfo(target_type=t, arrow_type=simple[t])


# dataset ------------------------------------------------------------------------------------------
def _col(name: str, ordinal: int, base: TdBaseType, **kw: Any) -> ColumnMeta:
    td = kw.pop("td", base.value)
    return ColumnMeta(name=name, ordinal=ordinal, base_type=base, td_type=td, td_type_code="X", **kw)


def _vc(name: str, ordinal: int, length: int, **kw: Any) -> ColumnMeta:
    return _col(name, ordinal, T.VARCHAR, length=length, td=f"VARCHAR({length})", **kw)


def _dec(name: str, ordinal: int, p: int, s: int) -> ColumnMeta:
    return _col(name, ordinal, T.DECIMAL, precision=p, scale=s, td=f"DECIMAL({p},{s})")


def _fk(cols: list[str], table: str, ref: list[str]) -> ForeignKey:
    return ForeignKey(columns=cols, ref_database=DB, ref_table=table, ref_columns=ref)


def olist_like(n: int = 200) -> dict[str, tuple[TableMeta, pa.Table]]:
    cities = ["sao paulo", "rio de janeiro", "belo horizonte", "curitiba"]
    cats = ["beleza_saude", "esporte_lazer", "informatica"]
    base = datetime(2017, 1, 1, 8, 0, 0)
    customers = pa.table(
        {
            "customer_id": [f"c{i:04d}" for i in range(n)],
            "customer_unique_id": [f"u{i // 2:04d}" for i in range(n)],
            "customer_zip_code_prefix": [f"{10000 + i:05d}" for i in range(n)],
            "customer_city": [cities[i % 4] for i in range(n)],
            "customer_state": ["SP"] * n,
            "contact_info": [f"user{i}@example.com" for i in range(n)],
        }
    )
    orders = pa.table(
        {
            "order_id": [f"o{i:04d}" for i in range(n)],
            "customer_id": [f"c{i:04d}" for i in range(n)],
            "order_status": ["delivered" if i % 7 else None for i in range(n)],
            "order_purchase_timestamp": pa.array(
                [base + timedelta(hours=i) for i in range(n)], pa.timestamp("us")
            ),
            "order_approved_at": pa.array(
                [datetime(2017, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(n)],
                pa.timestamp("us", tz="UTC"),
            ),
        }
    )
    items = pa.table(
        {
            "order_id": [f"o{i % n:04d}" for i in range(n * 2)],
            "order_item_id": pa.array([1 + i // n for i in range(n * 2)], pa.int32()),
            "product_id": [f"p{i % 50:03d}" for i in range(n * 2)],
            "price": pa.array(
                [Decimal(f"{10 + i % 90}.{i % 100:02d}") for i in range(n * 2)], pa.decimal128(10, 2)
            ),
            "shipping_limit_date": pa.array(
                [date(2017, 2, 1) + timedelta(days=i % 30) for i in range(n * 2)]
            ),
        }
    )
    products = pa.table(
        {
            "product_id": [f"p{i:03d}" for i in range(400)],
            "product_category_name": [
                ("pc_gamer" if i == 7 else None if i == 8 else cats[i % 3]) for i in range(400)
            ],
            "product_weight_g": pa.array([float(100 + i) for i in range(400)], pa.float64()),
        }
    )
    cat = pa.table(
        {"product_category_name": cats, "product_category_name_english": ["health", "sport", "it"]}
    )
    reviews = pa.table(
        {
            "review_id": [f"r{i // 2:04d}" for i in range(n)],  # duplicate review_id ...
            "order_id": [f"o{i:04d}" for i in range(n)],  # ... but unique (review_id, order_id)
            "review_score": pa.array([1 + i % 5 for i in range(n)], pa.int16()),
            "review_comment_message": [
                None if i % 3 else "Recebi o produto antes do prazo, muito bom mesmo, recomendo a loja"
                for i in range(n)
            ],
        }
    )
    metas = [
        TableMeta(
            database=DB,
            name="CUSTOMERS",
            columns=[
                _vc("customer_id", 1, 32, nullable=False),
                _vc("customer_unique_id", 2, 32),
                _vc("customer_zip_code_prefix", 3, 5),
                _vc("customer_city", 4, 60),
                _vc("customer_state", 5, 2),
                _vc("contact_info", 6, 80),
            ],
            primary_index=["customer_id"],
            primary_index_unique=True,
            unique_keys=[["customer_id"]],
        ),
        TableMeta(
            database=DB,
            name="ORDERS",
            columns=[
                _vc("order_id", 1, 32, nullable=False),
                _vc("customer_id", 2, 32),
                _vc("order_status", 3, 20),
                _col("order_purchase_timestamp", 4, T.TIMESTAMP, fractional_seconds=0),
                _col("order_approved_at", 5, T.TIMESTAMP_TZ, fractional_seconds=0),
            ],
            primary_index=["order_id"],
            primary_index_unique=True,
            unique_keys=[["order_id"]],
            partition_columns=["order_purchase_timestamp"],
            partition_expression="RANGE_N(...)",
            foreign_keys=[_fk(["customer_id"], "CUSTOMERS", ["customer_id"])],
        ),
        TableMeta(
            database=DB,
            name="ORDER_ITEMS",
            columns=[
                _vc("order_id", 1, 32),
                _col("order_item_id", 2, T.INTEGER),
                _vc("product_id", 3, 32),
                _dec("price", 4, 10, 2),
                _col("shipping_limit_date", 5, T.DATE),
            ],
            primary_index=["order_id"],
            unique_keys=[["order_id", "order_item_id"]],
            foreign_keys=[
                _fk(["order_id"], "ORDERS", ["order_id"]),
                _fk(["product_id"], "PRODUCTS", ["product_id"]),
            ],
        ),
        TableMeta(
            database=DB,
            name="PRODUCTS",
            columns=[
                _vc("product_id", 1, 32),
                _vc("product_category_name", 2, 60),
                _col("product_weight_g", 3, T.FLOAT),
            ],
            primary_index=["product_id"],
            primary_index_unique=True,
            unique_keys=[["product_id"]],
            foreign_keys=[
                _fk(["product_category_name"], "PRODUCT_CATEGORY_TRANSLATION", ["product_category_name"])
            ],
        ),
        TableMeta(
            database=DB,
            name="PRODUCT_CATEGORY_TRANSLATION",
            columns=[_vc("product_category_name", 1, 60), _vc("product_category_name_english", 2, 60)],
            primary_index=["product_category_name"],
            unique_keys=[["product_category_name"]],
        ),
        TableMeta(
            database=DB,
            name="ORDER_REVIEWS",
            columns=[
                _vc("review_id", 1, 32),
                _vc("order_id", 2, 32),
                _col("review_score", 3, T.SMALLINT),
                _vc("review_comment_message", 4, 300),
            ],
            primary_index=["review_id"],
            unique_keys=[["review_id", "order_id"]],
            foreign_keys=[_fk(["order_id"], "ORDERS", ["order_id"])],
        ),
    ]
    data = [customers, orders, items, products, cat, reviews]
    out = {}
    for m, d in zip(metas, data, strict=True):
        m.row_count = d.num_rows
        out[m.name] = (m, d)
    return out


# connectors ---------------------------------------------------------------------------------------
class FakeSource(SourceConnector):
    mode = "emulated"

    def __init__(self, tables: dict[str, tuple[TableMeta, pa.Table]]):
        self.tables = tables
        self.extract_calls: Counter[str] = Counter()
        self.sample_calls: Counter[str] = Counter()
        self._lock = threading.Lock()

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, mode="emulated", server_version="fake")

    def list_databases(self) -> list[str]:
        return [DB]

    def list_tables(self, database: str) -> list[SourceTableSummary]:
        return [
            SourceTableSummary(
                database=database,
                name=m.name,
                kind=m.kind,
                row_count=m.row_count,
                column_count=len(m.columns),
            )
            for m, _ in self.tables.values()
        ]

    def describe_table(self, database: str, table: str) -> TableMeta:
        return self.tables[table.upper()][0].model_copy(deep=True)

    def extract(self, database: str, table: str, columns: list[str] | None = None, batch_rows: int = 100_000):
        data = self.tables[table.upper()][1]
        data = data.select(columns) if columns else data
        with self._lock:
            # the planner samples a column subset with a small batch; a full extract asks for every column
            (
                self.extract_calls
                if data.num_columns == self.tables[table.upper()][1].num_columns
                else self.sample_calls
            )[table.upper()] += 1
        yield from data.to_batches(max_chunksize=batch_rows)

    def profile(self, database: str, table: str, spec: ProfileSpec) -> TableProfile:
        con = duckdb.connect()
        con.register("t", self.tables[table.upper()][1])
        rows = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        cols = {}
        from app.contracts.models import ColumnProfile

        for c in spec.null_columns:
            n = con.execute(f'SELECT COUNT(*) - COUNT("{c}") FROM t').fetchone()[0]
            cols[c] = ColumnProfile(column=c, null_count=n)
        for c in spec.numeric_columns:
            s, mn, mx = con.execute(
                f'SELECT CAST(SUM("{c}") AS VARCHAR), CAST(MIN("{c}") AS VARCHAR), '
                f'CAST(MAX("{c}") AS VARCHAR) FROM t'
            ).fetchone()
            cp = cols.setdefault(c, ColumnProfile(column=c, null_count=0))
            cp.sum, cp.min, cp.max = s, mn, mx
        return TableProfile(row_count=rows, columns=list(cols.values()))


class FakeTarget(TargetConnector):
    """Stores each loaded table as Parquet copies (REPLACE semantics) and profiles via DuckDB."""

    target_id = "fake"
    mode = "simulated"

    def __init__(self, meta: TargetMeta, root: Path, log: dict[str, Any]):
        super().__init__(meta, {}, {})
        self.root = root
        self.log = log

    def _dir(self, t: TablePlan) -> Path:
        return self.root / t.target_container / t.target_table

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, mode="simulated")

    def render_ddl(self, table: TablePlan) -> str:
        cols = ",\n  ".join(f"{c.target_name} {c.effective_type}" for c in table.columns)
        opts = " ".join(
            f"{k}={v}" for k, v in sorted(table.target_options.items()) if v not in (None, [], "")
        )
        return f"CREATE TABLE {table.target_container}.{table.target_table} (\n  {cols}\n) /* {opts} */"

    def ensure_container(self, container: str) -> None:
        (self.root / container).mkdir(parents=True, exist_ok=True)

    def create_table(self, table: TablePlan) -> None:
        self._dir(table).mkdir(parents=True, exist_ok=True)

    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        d = self._dir(table)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        for i, f in enumerate(files):
            shutil.copy(f, d / f"part-{i:05d}.parquet")
        rows = sum(pq.ParquetFile(f).metadata.num_rows for f in files)
        self.log.setdefault("loads", Counter())[table.name] += 1
        return LoadResult(rows_loaded=rows, load_id=load_id, duration_s=0.01, method="fake_copy")

    def profile(self, table: TablePlan, spec: ProfileSpec) -> TableProfile:
        files = sorted(self._dir(table).glob("*.parquet"))
        schema = pq.read_schema(files[0]) if files else pa.schema([])
        if self.log.get("corrupt") == table.name and files:
            t = pq.read_table(files[0])
            pq.write_table(t.slice(1), files[0])
        return profile_parquet(files, schema, spec)

    def drop_table(self, table: TablePlan) -> None:
        shutil.rmtree(self._dir(table), ignore_errors=True)

    def access_script(self, plan: MigrationPlan) -> str:
        return "\n".join(
            f"GRANT SELECT ON {t.target_container}.{t.target_table} TO analyst;" for t in plan.tables
        )
