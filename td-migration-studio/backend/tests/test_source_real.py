"""RealTeradataSource against a mocked `teradatasql` connection.

The dictionary is served by SQLite (attached as schema DBC) populated with the very rows the seeder writes
into the emulator's `dbc` schema, so this also proves real and emulated modes yield identical TableMeta.
"""

import datetime as dt
import sqlite3
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from app.connectors.source.real import RealTeradataSource
from app.connectors.source.seed import dictionary_rows, load_inputs
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
VIEWS = {
    "tablesv": ("TablesV", "DatabaseName, TableName, TableKind, ProtectionType, JournalFlag, CheckOpt, "
                "CreatorName, CommentString, RequestText, CreateTimeStamp, LastAlterTimeStamp"),
    "columnsv": ("ColumnsV", "DatabaseName, TableName, ColumnName, ColumnId, ColumnType, ColumnLength, "
                 "DecimalTotalDigits, DecimalFractionalDigits, CharType, UpperCaseFlag, Nullable, "
                 "DefaultValue, "
                 "Compressible, CompressValueList, ColumnFormat, CommentString"),
    "indicesv": ("IndicesV", "DatabaseName, TableName, IndexNumber, IndexType, UniqueFlag, IndexName, "
                 "ColumnName, ColumnPosition"),
    "parts": ("PartitioningConstraintsV", "DatabaseName, TableName, IndexNumber, PartitioningLevels, "
              "ConstraintText"),
    "ri": ("All_RI_ChildrenV", "IndexID, IndexName, ChildDB, ChildTable, ChildKeyColumn, ParentDB, "
           "ParentTable, ParentKeyColumn, InconsistencyFlag"),
    "stats": ("TableStatsV", "DatabaseName, TableName, IndexNumber, RowCount, LastCollectTimeStamp"),
}  # fmt: skip


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.cur, self.description = conn, conn.db.cursor(), None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cur.close()

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if sql.startswith("SHOW TABLE"):
            raise RuntimeError("[Error 3807] SHOW not supported by this mock")
        if sql.startswith("SELECT") and ' FROM "RETAIL_DW"' in sql:  # data request -> canned rows
            self.description, self._rows = [("x",)], list(self.conn.data)
            return
        self.cur.execute(sql, params or [])
        self.description, self._rows = self.cur.description, None

    def fetchall(self):
        return self.cur.fetchall() if self._rows is None else self._rows

    def fetchmany(self, n):
        if self._rows is None:
            return self.cur.fetchmany(n)
        self.conn.fetch_sizes.append(n)
        out, self._rows = self._rows[:n], self._rows[n:]
        return out


class FakeConnection:
    def __init__(self, db, data=()):
        self.db, self.data, self.executed, self.fetch_sizes, self.closed = db, data, [], [], 0

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed += 1


@pytest.fixture(scope="module")
def inputs():
    return load_inputs(ROOT / "source" / "ddl" / "teradata", ROOT / "data" / "olist")


@pytest.fixture
def dbc(inputs):
    database, tables, _ = inputs
    counts = {t.parsed.meta.name: 1000 + i for i, t in enumerate(tables)}
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("ATTACH ':memory:' AS DBC")
    for key, (view, cols) in VIEWS.items():
        db.execute(f"CREATE TABLE DBC.{view} ({cols})")
        for row in dictionary_rows(database, tables, counts)[key]:
            db.execute(f"INSERT INTO DBC.{view} VALUES ({', '.join('?' * len(row))})", row)
    db.execute(
        "CREATE TABLE DBC.TableSizeV (Vproc, DatabaseName, AccountName, TableName, CurrentPerm, PeakPerm)"
    )
    for i, t in enumerate(tables):  # two AMPs per table
        for vproc in (0, 1):
            db.execute("INSERT INTO DBC.TableSizeV VALUES (?, 'RETAIL_DW', 'DBC', ?, ?, ?)",
                       (vproc, t.parsed.meta.name, 512 * (i + 1), 512 * (i + 1)))  # fmt: skip
    db.execute("CREATE TABLE DBC.DBCInfoV (InfoKey, InfoData)")
    db.execute("INSERT INTO DBC.DBCInfoV VALUES ('VERSION', '17.20.03.09')")
    return db, counts, {t.parsed.meta.name: t.parsed.meta for t in tables}


def _source(conn, **kw):
    return RealTeradataSource(
        Settings(td_mode="real", td_host="td.example", td_user="u", **kw), connect=lambda: conn
    )


def test_metadata_matches_parsed_ddl(dbc):
    db, counts, metas = dbc
    src = _source(FakeConnection(db))
    assert src.mode == "real"
    assert src.list_databases() == ["RETAIL_DW"]
    summaries = {t.name: t for t in src.list_tables("retail_dw")}
    assert set(summaries) == set(metas)
    assert summaries["ORDERS"].row_count == counts["ORDERS"] and summaries["ORDERS"].size_bytes > 0
    for name, expected in metas.items():
        got = src.describe_table("RETAIL_DW", name)
        assert got.model_dump(exclude={"row_count", "size_bytes"}) == expected.model_dump(
            exclude={"row_count", "size_bytes"}
        ), name
        assert got.row_count == counts[name]
    orders = src.describe_table("RETAIL_DW", "ORDERS")
    assert orders.size_bytes == 2 * 512 * 5  # summed over AMPs
    assert orders.partition_columns == ["order_purchase_timestamp"]
    assert orders.ddl.startswith("CREATE MULTISET TABLE RETAIL_DW.ORDERS")  # SHOW TABLE fallback


def test_queries_target_real_dbc_views(dbc):
    conn = FakeConnection(dbc[0])
    _source(conn).describe_table("RETAIL_DW", "ORDER_ITEMS")
    sql = " ".join(s for s, _ in conn.executed)
    for view in ("DBC.TablesV", "DBC.ColumnsV", "DBC.IndicesV", "DBC.All_RI_ChildrenV", "DBC.TableSizeV"):
        assert view in sql
    assert all("?" in s for s, p in conn.executed if p)


def test_extract_chunks_with_fetchmany(dbc):
    rows = [
        (f"r{i}", f"o{i}", 5, None, "ótimo", dt.datetime(2018, 1, 1, 10), dt.datetime(2018, 1, 2, 0, 46, 59,
         tzinfo=dt.timezone(dt.timedelta(hours=-3))))
        for i in range(5)
    ]  # fmt: skip
    data_conn = FakeConnection(dbc[0], rows)
    meta_conn = FakeConnection(dbc[0])
    conns = iter([meta_conn, data_conn])
    src = RealTeradataSource(Settings(td_host="h", td_user="u"), connect=lambda: next(conns))
    batches = list(src.extract("RETAIL_DW", "ORDER_REVIEWS", batch_rows=2))
    assert [b.num_rows for b in batches] == [2, 2, 1] and data_conn.fetch_sizes[:3] == [2, 2, 2]
    assert data_conn.closed == 1
    schema = batches[0].schema
    assert schema.field("review_score").type == pa.int8()
    assert schema.field("review_creation_date").type == pa.timestamp("us")
    assert schema.field("review_answer_timestamp").type == pa.timestamp("us", tz="UTC")
    sql = data_conn.executed[0][0]
    assert 'TRIM(TRAILING FROM "review_id")' in sql and 'FROM "RETAIL_DW"."ORDER_REVIEWS"' in sql
    first = pa.Table.from_batches(batches).to_pylist()[0]
    assert first["review_answer_timestamp"] == dt.datetime(2018, 1, 2, 3, 46, 59, tzinfo=dt.timezone.utc)


def test_extract_number_and_decimal(dbc):
    rows = [("01037", Decimal("-23.545621"), None, "são paulo", "SP")]
    conns = iter([FakeConnection(dbc[0]), FakeConnection(dbc[0], rows)])
    src = RealTeradataSource(Settings(td_host="h", td_user="u"), connect=lambda: next(conns))
    (batch,) = src.extract("RETAIL_DW", "GEOLOCATION", columns=None)
    assert batch.schema.field("geolocation_lat").type == pa.decimal128(38, 15)
    assert batch.column("geolocation_lat")[0].as_py() == Decimal("-23.545621")


def test_test_connection(dbc):
    ok = _source(FakeConnection(dbc[0])).test_connection()
    assert ok.ok and ok.mode == "real" and ok.server_version == "17.20.03.09" and ok.latency_ms >= 0

    def boom():
        raise OSError("connection refused")

    bad = RealTeradataSource(Settings(td_host="h", td_user="u"), connect=boom).test_connection()
    assert not bad.ok and "connection refused" in bad.message


def test_missing_credentials_reported():
    res = RealTeradataSource(Settings(td_host=None, td_user=None)).test_connection()
    assert not res.ok and "TD_HOST" in res.message
