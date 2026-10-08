"""Idempotent seeder for the emulated Teradata (`python -m app.connectors.source.seed [--force]`).

Parses the Teradata DDL listed in source/ddl/teradata/manifest.yaml, creates the physical tables in
Postgres schema `<database>` (retail_dw), bulk-loads the gzipped Olist CSVs with COPY and fills the emulated
DBC dictionary (schema `dbc`). Everything runs in one transaction; `dbc.seed_marker` stores a hash of the
inputs so re-running is a no-op unless the DDL/data/seeder changed or `--force` is given.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
import yaml
from psycopg import sql as pgsql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ...contracts.models import ColumnMeta, TdBaseType
from ...settings import Settings, get_settings
from .catalog import COLUMNSV_FIELDS, column_to_dbc, partition_check_text
from .td_ddl import ParsedTable, parse_ddl

log = logging.getLogger("tdemu.seed")
T = TdBaseType
SEED_FORMAT_VERSION = "1"  # bump when the emulated layout changes, to force a re-seed
TD_VERSION = "17.20.03.09"
LOCK_ID = 7_155_301  # pg advisory lock key
COPY_CHUNK = 1 << 20

DBC_DDL = """
CREATE SCHEMA dbc;
CREATE TABLE dbc.dbcinfov (InfoKey varchar(30) PRIMARY KEY, InfoData varchar(16384));
CREATE TABLE dbc.tablesv (
  DatabaseName varchar(128), TableName varchar(128), TableKind char(1), ProtectionType char(1),
  JournalFlag char(2), CheckOpt char(1), CreatorName varchar(128), CommentString varchar(255),
  RequestText text, CreateTimeStamp timestamp(0), LastAlterTimeStamp timestamp(0),
  PRIMARY KEY (DatabaseName, TableName));
CREATE TABLE dbc.columnsv (
  DatabaseName varchar(128), TableName varchar(128), ColumnName varchar(128), ColumnId smallint,
  ColumnType char(2), ColumnLength integer, DecimalTotalDigits smallint, DecimalFractionalDigits smallint,
  CharType smallint, UpperCaseFlag char(1), Nullable char(1), DefaultValue text, Compressible char(1),
  CompressValueList text, ColumnFormat varchar(128), CommentString varchar(255),
  PRIMARY KEY (DatabaseName, TableName, ColumnName));
CREATE TABLE dbc.indicesv (
  DatabaseName varchar(128), TableName varchar(128), IndexNumber smallint, IndexType char(1),
  UniqueFlag char(1), IndexName varchar(128), ColumnName varchar(128), ColumnPosition smallint,
  PRIMARY KEY (DatabaseName, TableName, IndexNumber, ColumnPosition));
CREATE TABLE dbc.partitioningconstraintsv (
  DatabaseName varchar(128), TableName varchar(128), IndexNumber smallint, PartitioningLevels smallint,
  ConstraintText text);
CREATE TABLE dbc.all_ri_childrenv (
  IndexID smallint, IndexName varchar(128), ChildDB varchar(128), ChildTable varchar(128),
  ChildKeyColumn varchar(128), ParentDB varchar(128), ParentTable varchar(128), ParentKeyColumn varchar(128),
  InconsistencyFlag char(1));
CREATE TABLE dbc.tablestatsv (
  DatabaseName varchar(128), TableName varchar(128), IndexNumber smallint, RowCount bigint,
  LastCollectTimeStamp timestamp(0));
CREATE VIEW dbc.tablesizev AS
  SELECT 0 AS Vproc, t.DatabaseName, 'DBC'::varchar(128) AS AccountName, t.TableName,
         pg_total_relation_size(format('%I.%I', lower(t.DatabaseName), lower(t.TableName))::regclass)::bigint
           AS CurrentPerm,
         pg_total_relation_size(format('%I.%I', lower(t.DatabaseName), lower(t.TableName))::regclass)::bigint
           AS PeakPerm
  FROM dbc.tablesv t WHERE t.TableKind = 'T';
CREATE TABLE dbc.seed_marker (
  id int PRIMARY KEY, input_hash text NOT NULL, seeded_at timestamptz NOT NULL DEFAULT now(),
  seconds double precision, row_counts jsonb);
"""


@dataclass
class SeedResult:
    skipped: bool
    input_hash: str
    row_counts: dict[str, int]
    seconds: float


# --------------------------------------------------------------------------------------------------
# Teradata -> PostgreSQL physical types
# --------------------------------------------------------------------------------------------------


def pg_type(c: ColumnMeta) -> str:
    b, fs = c.base_type, c.fractional_seconds
    simple = {
        T.BYTEINT: "smallint", T.SMALLINT: "smallint", T.INTEGER: "integer", T.BIGINT: "bigint",
        T.FLOAT: "double precision", T.CLOB: "text", T.BYTE: "bytea", T.VARBYTE: "bytea", T.BLOB: "bytea",
        T.DATE: "date", T.INTERVAL: "interval", T.PERIOD: "text", T.JSON: "jsonb", T.XML: "xml",
    }  # fmt: skip
    if b in simple:
        return simple[b]
    if b == T.DECIMAL:
        return f"numeric({c.precision},{c.scale})"
    if b == T.NUMBER:
        return "numeric" if c.precision is None else f"numeric({c.precision},{c.scale or 0})"
    if b == T.CHAR:
        return f"char({c.length})"
    if b == T.VARCHAR:
        return f"varchar({c.length})"
    return {T.TIME: "time", T.TIME_TZ: "timetz", T.TIMESTAMP: "timestamp", T.TIMESTAMP_TZ: "timestamptz"}[
        b
    ] + (f"({fs})" if fs is not None else "")


def physical_ddl(pt: ParsedTable) -> list[pgsql.Composable]:
    m = pt.meta
    schema, table = pgsql.Identifier(m.database.lower()), pgsql.Identifier(m.name.lower())
    cols = []
    for c in m.columns:
        col = pgsql.SQL("{} {}{}").format(
            pgsql.Identifier(c.name.lower()),
            pgsql.SQL(pg_type(c)),
            pgsql.SQL("" if c.nullable else " NOT NULL"),
        )
        if c.base_type == T.BYTEINT:
            col = pgsql.SQL("{} CHECK ({} BETWEEN -128 AND 127)").format(
                col, pgsql.Identifier(c.name.lower())
            )
        cols.append(col)
    stmts: list[pgsql.Composable] = [
        pgsql.SQL("CREATE TABLE {}.{} ({})").format(schema, table, pgsql.SQL(", ").join(cols))
    ]
    return stmts


def unique_index_ddl(pt: ParsedTable) -> list[pgsql.Composable]:
    """UPI / USI uniqueness is enforced by Teradata; emulate with unique btree indexes (built after load)."""
    m, out = pt.meta, []
    for idx in pt.indexes:
        if idx.unique:
            name = f"{m.name.lower()}_{(idx.name or f'idx{idx.number}').lower()}"[:63]
            out.append(
                pgsql.SQL("CREATE UNIQUE INDEX {} ON {}.{} ({})").format(
                    pgsql.Identifier(name),
                    pgsql.Identifier(m.database.lower()),
                    pgsql.Identifier(m.name.lower()),
                    pgsql.SQL(", ").join(pgsql.Identifier(c.lower()) for c in idx.columns),
                )
            )
    return out


# --------------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------------


@dataclass
class TableInput:
    parsed: ParsedTable
    seed_file: Path
    timezone: str | None


def load_inputs(ddl_dir: Path, seed_dir: Path) -> tuple[str, list[TableInput], str]:
    """-> (database, tables in manifest order, input hash)."""
    manifest_path = ddl_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    database = manifest["database"]
    h = hashlib.sha256(f"seed-format:{SEED_FORMAT_VERSION}".encode())
    h.update(manifest_path.read_bytes())
    tables = []
    for name, spec in manifest["tables"].items():
        ddl_path, seed_path = ddl_dir / spec["ddl"], seed_dir / spec["seed"]
        parsed = [p for p in parse_ddl(ddl_path.read_text(), database) if p.meta.name.upper() == name.upper()]
        if not parsed:
            raise ValueError(f"{ddl_path.name}: no CREATE TABLE for {name}")
        tz = spec.get("timezone")
        if tz is not None and not re.fullmatch(r"[+-]\d{2}:\d{2}", tz):
            raise ValueError(f"{name}: timezone must look like '-03:00', got {tz!r}")
        h.update(ddl_path.read_bytes())
        with seed_path.open("rb") as f:
            for chunk in iter(lambda: f.read(COPY_CHUNK), b""):
                h.update(chunk)
        tables.append(TableInput(parsed[0], seed_path, tz))
    return database, tables, h.hexdigest()


# --------------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------------


def copy_csv(cur: psycopg.Cursor, ti: TableInput) -> None:
    m = ti.parsed.meta
    with gzip.open(ti.seed_file, "rb") as f:
        header_line = f.readline().decode("utf-8-sig")
        header = next(csv.reader([header_line]))
        ddl_cols = {c.name.lower() for c in m.columns}
        if {h.lower() for h in header} != ddl_cols:
            raise ValueError(
                f"{ti.seed_file.name}: CSV header {header} does not match DDL columns {sorted(ddl_cols)}"
            )
        cols = pgsql.SQL(", ").join(pgsql.Identifier(h.lower()) for h in header)
        stmt = pgsql.SQL(
            "COPY {}.{} ({}) FROM STDIN WITH (FORMAT csv, NULL '', FORCE_NULL ({}), FREEZE)"
        ).format(pgsql.Identifier(m.database.lower()), pgsql.Identifier(m.name.lower()), cols, cols)
        if ti.timezone:
            cur.execute(pgsql.SQL("SET LOCAL TIME ZONE INTERVAL {} HOUR TO MINUTE").format(ti.timezone))
        with cur.copy(stmt) as cp:
            for chunk in iter(lambda: f.read(COPY_CHUNK), b""):
                cp.write(chunk)
        if ti.timezone:
            cur.execute("SET LOCAL TIME ZONE 'UTC'")


def dictionary_rows(
    database: str, tables: list[TableInput], counts: dict[str, int]
) -> dict[str, list[tuple]]:
    rows: dict[str, list[tuple]] = {
        k: [] for k in ("tablesv", "columnsv", "indicesv", "parts", "ri", "stats")
    }
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    for ti in tables:
        pt, m = ti.parsed, ti.parsed.meta
        key = (m.database, m.name)
        rows["tablesv"].append(
            (*key, "T", "N", "NN", "Y" if m.kind == "SET" else "N", "DBC", pt.comment, m.ddl, now, now)
        )
        for c in m.columns:
            r = column_to_dbc(c)
            rows["columnsv"].append((*key, *(r[f] for f in COLUMNSV_FIELDS)))
        for idx in pt.indexes:
            for pos, col in enumerate(idx.columns, start=1):
                rows["indicesv"].append(
                    (*key, idx.number, idx.kind, "Y" if idx.unique else "N", idx.name, col, pos)
                )
        if m.partition_expression:
            rows["parts"].append((*key, 1, 1, partition_check_text(m.partition_expression)))
        for n, (fk, fk_name) in enumerate(zip(m.foreign_keys, pt.fk_names, strict=True), start=1):
            for child, parent in zip(fk.columns, fk.ref_columns, strict=True):
                rows["ri"].append(
                    (
                        n,
                        fk_name,
                        *key,
                        child,
                        fk.ref_database,
                        fk.ref_table,
                        parent,
                        "N" if fk.enforced else "Y",
                    )
                )
        rows["stats"].append((*key, 1, counts[m.name], now))
    return rows


_INSERTS = {
    "tablesv": "INSERT INTO dbc.tablesv VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
    "columnsv": "INSERT INTO dbc.columnsv VALUES (" + ", ".join(["%s"] * 16) + ")",
    "indicesv": "INSERT INTO dbc.indicesv VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
    "parts": "INSERT INTO dbc.partitioningconstraintsv VALUES (%s, %s, %s, %s, %s)",
    "ri": "INSERT INTO dbc.all_ri_childrenv VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
    "stats": "INSERT INTO dbc.tablestatsv VALUES (%s, %s, %s, %s, %s)",
}


def ensure_database(dsn: str) -> None:
    """Create the target database if missing (e.g. an existing pg volume that predates db/init)."""
    info = conninfo_to_dict(dsn)
    dbname = info.get("dbname")
    if not dbname:
        return
    with psycopg.connect(make_conninfo(dsn, dbname="postgres"), autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [dbname]).fetchone():
            conn.execute(pgsql.SQL("CREATE DATABASE {}").format(pgsql.Identifier(dbname)))
            log.info("created database %s", dbname)


def _connect_with_retry(dsn: str, attempts: int = 20) -> psycopg.Connection:
    for i in range(attempts):
        try:
            ensure_database(dsn)
            return psycopg.connect(dsn)
        except psycopg.OperationalError:
            if i == attempts - 1:
                raise
            time.sleep(1.5)
    raise AssertionError("unreachable")


def _current_hash(cur: psycopg.Cursor) -> str | None:
    if not cur.execute("SELECT to_regclass('dbc.seed_marker')").fetchone()[0]:
        return None
    row = cur.execute("SELECT input_hash FROM dbc.seed_marker WHERE id = 1").fetchone()
    return row[0] if row else None


def seed(
    settings: Settings | None = None, *, dsn: str | None = None, force: bool = False,
    ddl_dir: Path | None = None, seed_dir: Path | None = None,
) -> SeedResult:  # fmt: skip
    settings = settings or get_settings()
    dsn = dsn or settings.td_emu_dsn
    t0 = time.perf_counter()
    database, tables, input_hash = load_inputs(ddl_dir or settings.ddl_dir, seed_dir or settings.seed_dir)
    with _connect_with_retry(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_ID])
        if not force and _current_hash(cur) == input_hash:
            counts = dict(cur.execute("SELECT TableName, RowCount FROM dbc.tablestatsv").fetchall())
            log.info("emulated Teradata already seeded (hash %s) - nothing to do", input_hash[:12])
            return SeedResult(True, input_hash, counts, time.perf_counter() - t0)
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        cur.execute("SET LOCAL maintenance_work_mem = '256MB'")
        schema = pgsql.Identifier(database.lower())
        cur.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(schema))
        cur.execute("DROP SCHEMA IF EXISTS dbc CASCADE")
        cur.execute(pgsql.SQL("CREATE SCHEMA {}").format(schema))
        cur.execute(DBC_DDL)
        counts: dict[str, int] = {}
        for ti in tables:
            t1 = time.perf_counter()
            for stmt in physical_ddl(ti.parsed):
                cur.execute(stmt)
            copy_csv(cur, ti)
            for stmt in unique_index_ddl(ti.parsed):
                cur.execute(stmt)
            rel = pgsql.SQL("{}.{}").format(schema, pgsql.Identifier(ti.parsed.meta.name.lower()))
            counts[ti.parsed.meta.name] = cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {}").format(rel)
            ).fetchone()[0]
            log.info("loaded %-30s %9d rows in %.1fs", ti.parsed.meta.fqn, counts[ti.parsed.meta.name],
                     time.perf_counter() - t1)  # fmt: skip
        for key, rows in dictionary_rows(database, tables, counts).items():
            if rows:
                cur.executemany(_INSERTS[key], rows)
        cur.executemany(
            "INSERT INTO dbc.dbcinfov VALUES (%s, %s)",
            [
                ("VERSION", f"{TD_VERSION} (emulated on PostgreSQL {conn.info.server_version // 10000})"),
                ("RELEASE", TD_VERSION),
                ("LANGUAGE SUPPORT MODE", "Standard"),
            ],
        )
        seconds = time.perf_counter() - t0
        cur.execute(
            "INSERT INTO dbc.seed_marker (id, input_hash, seconds, row_counts) VALUES (1, %s, %s, %s)",
            [input_hash, seconds, json.dumps(counts)],
        )
        conn.commit()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(pgsql.SQL("ANALYZE"))  # planner stats only; not part of the seeded state
    seconds = time.perf_counter() - t0
    log.info("seeded %s: %d tables, %d rows in %.1fs", database, len(counts), sum(counts.values()), seconds)
    return SeedResult(False, input_hash, counts, seconds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="re-seed even if inputs are unchanged")
    ap.add_argument("--dsn", help="override TD_EMU_DSN")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    result = seed(dsn=args.dsn, force=args.force)
    print(
        json.dumps(
            {"skipped": result.skipped, "rows": result.row_counts, "seconds": round(result.seconds, 1)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
