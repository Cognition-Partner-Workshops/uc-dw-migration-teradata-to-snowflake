"""Execution engines for the dual run.

Both emulators execute on DuckDB but go through completely separate code paths:
the legacy side interprets the *original Teradata SQL*, the target side runs the
*converted Snowflake SQL* exactly as the converter produced it. Every rewrite the
emulators apply is recorded so it can be disclosed in the evidence pack.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from .sqltext import matching_paren, object_of, rewrite_calls, split_args, split_statements, strip_comments


@dataclass
class Column:
    name: str
    declared_type: str
    nullable: bool = True


@dataclass
class TableDef:
    name: str
    columns: list[Column]


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[tuple[Any, ...]]


@dataclass
class LoadedObject:
    kind: str
    name: str
    source_sql: str
    executed_sql: str


class EngineError(RuntimeError):
    pass


@dataclass
class DuckDBEngine:
    """Base class: a private in-memory DuckDB database plus a rewrite log."""

    as_of: date
    label: str = "engine"
    notes: dict[str, set[str]] = field(default_factory=dict)
    tables: dict[str, TableDef] = field(default_factory=dict)
    objects: dict[str, LoadedObject] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        self._current_notes: set[str] = set()

    def _ensure_schema(self, name: str) -> None:
        if "." in name:
            self.con.execute(f'CREATE SCHEMA IF NOT EXISTS {name.split(".")[0]}')

    def translate(self, stmt: str) -> tuple[str, str, str, TableDef | None] | None:
        raise NotImplementedError

    def _note(self, message: str) -> None:
        self._current_notes.add(message)

    def load_script(self, sql: str) -> list[LoadedObject]:
        loaded: list[LoadedObject] = []
        for stmt in split_statements(strip_comments(sql)):
            self._current_notes = set()
            translated = self.translate(stmt)
            if translated is None:
                self.skipped.append(" ".join(stmt.split())[:80])
                continue
            kind, name, ddl, table = translated
            self._ensure_schema(name)
            try:
                self.con.execute(ddl)
            except duckdb.Error as e:
                raise EngineError(f"{self.label}: failed to create {kind} {name}: {e}") from e
            if table is not None:
                self.tables[name] = table
            self.notes[name] = self._current_notes
            obj = LoadedObject(kind, name, stmt, ddl)
            self.objects[name] = obj
            loaded.append(obj)
        return loaded

    def insert_rows(self, table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", encoding="utf-8", delete=False) as fh:
            writer = csv.writer(fh, delimiter="|", quoting=csv.QUOTE_MINIMAL)
            for row in rows:
                writer.writerow(["\\N" if v is None else v for v in row])
        try:
            self.con.execute(
                f"COPY {table} ({', '.join(columns)}) FROM '{fh.name}' "
                "(FORMAT CSV, DELIMITER '|', HEADER FALSE, NULL '\\N', QUOTE '\"')"
            )
        finally:
            os.unlink(fh.name)

    def query(self, sql: str) -> QueryResult:
        rel = self.con.sql(sql)
        return QueryResult(list(rel.columns), [str(t) for t in rel.types], rel.fetchall())

    def column_types(self, name: str) -> dict[str, str]:
        rel = self.con.sql(f"SELECT * FROM {name} LIMIT 0")
        return {c.upper(): str(t) for c, t in zip(rel.columns, rel.types)}


# --------------------------------------------------------------------------- Teradata

_TD_TABLE_OPTIONS = re.compile(r"^\s*,?\s*(NO\s+)?(FALLBACK|BEFORE\s+JOURNAL|AFTER\s+JOURNAL|LOG)\b", re.I)
_TD_TYPE = re.compile(r"^([A-Za-z_]+(?:\s+PRECISION)?)(\s*\([^)]*\))?", re.I)
_TD_FORMAT_PHRASE = re.compile(r"\(\s*FORMAT\s+'[^']*'\s*\)", re.I)
_TD_CASESPECIFIC_PHRASE = re.compile(r"\(\s*(NOT\s+)?CASESPECIFIC\s*\)", re.I)


def _td_column_type(raw: str) -> tuple[str, str]:
    """Return (declared Teradata type, DuckDB type)."""
    m = _TD_TYPE.match(raw.strip())
    if not m:
        raise EngineError(f"cannot parse Teradata column type: {raw!r}")
    base = m.group(1).upper()
    args = (m.group(2) or "").replace(" ", "")
    declared = base + args
    if base == "BYTEINT":
        return declared, "TINYINT"
    if base in {"TIMESTAMP", "TIME"}:
        return declared, base
    if base in {"CHAR", "CHARACTER", "VARCHAR"}:
        return declared, "VARCHAR"
    if base in {"DECIMAL", "NUMERIC"}:
        return declared, f"DECIMAL{args or '(5,0)'}"
    return declared, base + args


class TeradataEmulator(DuckDBEngine):
    """Interprets original Teradata DDL/SQL with Teradata semantics on DuckDB."""

    def __init__(self, as_of: date) -> None:
        super().__init__(as_of=as_of, label="legacy (Teradata emulation)")

    def translate(self, stmt: str):
        obj = object_of(stmt)
        if obj is None:
            return None
        kind, name = obj
        if kind == "TABLE":
            table = self._parse_table(stmt, name)
            cols = ", ".join(
                f"{c.name} {_td_column_type(c.declared_type)[1]}{'' if c.nullable else ' NOT NULL'}"
                for c in table.columns
            )
            self._note("Teradata physical options (SET/MULTISET, PI/PPI, COMPRESS, FORMAT, statistics) "
                           "are storage-only and are not executed")
            return kind, name, f"CREATE TABLE {name} ({cols})", table
        return kind, name, f"CREATE OR REPLACE VIEW {name} AS {self._rewrite_query(stmt)}", None

    def _parse_table(self, stmt: str, name: str) -> TableDef:
        start = stmt.upper().find(name) + len(name)
        open_idx = stmt.index("(", start)
        body = stmt[open_idx + 1 : matching_paren(stmt, open_idx)]
        columns: list[Column] = []
        for part in split_args(body):
            tokens = part.split(None, 1)
            if len(tokens) < 2:
                continue
            col_name, rest = tokens[0].upper(), tokens[1]
            declared, _ = _td_column_type(rest)
            nullable = not re.search(r"\bNOT\s+NULL\b", rest, re.I)
            columns.append(Column(col_name, declared, nullable))
        return TableDef(name, columns)

    def _rewrite_query(self, stmt: str) -> str:
        sql = re.sub(r"^.*?\bAS\b", "", stmt, count=1, flags=re.I | re.S)
        sql = re.sub(r"\bLOCKING\s+ROW\s+FOR\s+ACCESS\b", "", sql, flags=re.I)
        sql = re.sub(r"\bSEL\b", "SELECT", sql, flags=re.I)
        sql = _TD_CASESPECIFIC_PHRASE.sub("", sql)
        sql = re.sub(r"TRIM\(\s*([\w.]+)\s*\(\s*FORMAT\s+'[^']*'\s*\)\s*\)",
                     r"TRIM(CAST(\1 AS VARCHAR))", sql, flags=re.I)
        if _TD_FORMAT_PHRASE.search(sql):
            self._note("(FORMAT '...') phrases are display-only in Teradata; result columns keep "
                           "their numeric type for SQL clients")
            sql = _TD_FORMAT_PHRASE.sub("", sql)
        sql = rewrite_calls(sql, "ZEROIFNULL", lambda a: f"COALESCE({a[0]}, 0)")
        sql = rewrite_calls(sql, "NULLIFZERO", lambda a: f"NULLIF({a[0]}, 0)")
        if re.search(r"\bHASHROW\s*\(", sql, re.I):
            self._note("HASHROW emulated with a deterministic hash; values are not Teradata row hashes")
            sql = rewrite_calls(sql, "HASHROW", lambda a: f"hash({', '.join(a)})")
        if re.search(r"\b(CSUM|MAVG|MSUM)\s*\(", sql, re.I):
            self._note("CSUM/MAVG/MSUM interpreted as ANSI windows over the whole result ordered by "
                           "the sort-key argument (no reset); confirm against production Teradata")
            sql = rewrite_calls(
                sql, "CSUM",
                lambda a: f"SUM({a[0]}) OVER (ORDER BY {', '.join(a[1:])} ROWS UNBOUNDED PRECEDING)")
            sql = rewrite_calls(
                sql, "MAVG",
                lambda a: f"AVG({a[0]}) OVER (ORDER BY {', '.join(a[2:])} "
                          f"ROWS BETWEEN {int(a[1]) - 1} PRECEDING AND CURRENT ROW)")
            sql = rewrite_calls(
                sql, "MSUM",
                lambda a: f"SUM({a[0]}) OVER (ORDER BY {', '.join(a[2:])} "
                          f"ROWS BETWEEN {int(a[1]) - 1} PRECEDING AND CURRENT ROW)")
        sql = rewrite_calls(
            sql, "ADD_MONTHS", lambda a: f"CAST(({a[0]}) + to_months({a[1]}) AS DATE)")
        sql = re.sub(r"\bCURRENT_DATE\b", f"DATE '{self.as_of.isoformat()}'", sql, flags=re.I)
        sql = re.sub(r"\bCURRENT_TIMESTAMP(\s*\(\s*\d*\s*\))?", f"TIMESTAMP '{self.as_of.isoformat()} 00:00:00'",
                     sql, flags=re.I)
        return sql


# --------------------------------------------------------------------------- Snowflake


def _sf_type_to_duckdb(dt: exp.DataType) -> str:
    t = dt.this
    T = exp.DataType.Type
    params = [p.sql("snowflake") for p in dt.expressions]
    if t in {T.CHAR, T.NCHAR, T.VARCHAR, T.NVARCHAR, T.TEXT}:
        return "VARCHAR"
    if t in {T.DECIMAL}:
        if not params:
            return "DECIMAL(38,0)"
        return f"DECIMAL({', '.join(params)})"
    if t in {T.TIMESTAMP, T.TIMESTAMPNTZ, T.DATETIME}:
        return "TIMESTAMP"
    if t in {T.TIMESTAMPTZ, T.TIMESTAMPLTZ}:
        return "TIMESTAMPTZ"
    if t == T.TIME:
        return "TIME"
    return exp.DataType(this=t).sql("duckdb")


class SnowflakeEmulator(DuckDBEngine):
    """Runs converted Snowflake SQL on DuckDB via sqlglot, keeping Snowflake semantics."""

    def __init__(self, as_of: date) -> None:
        super().__init__(as_of=as_of, label="target (Snowflake emulation)")

    def translate(self, stmt: str):
        obj = object_of(stmt)
        if obj is None:
            return None
        kind, name = obj
        try:
            tree = sqlglot.parse_one(stmt, read="snowflake")
        except sqlglot.errors.ParseError as e:
            raise EngineError(f"{self.label}: cannot parse {kind} {name}: {e}") from e
        if kind == "TABLE":
            return kind, name, *self._table(tree, name)
        query = tree.expression
        if query is None:
            raise EngineError(f"{self.label}: view {name} has no query")
        query = query.transform(self._pin_and_patch)
        return kind, name, f"CREATE OR REPLACE VIEW {name} AS {query.sql('duckdb')}", None

    def _table(self, tree: exp.Expression, name: str) -> tuple[str, TableDef]:
        schema = tree.this
        cols: list[str] = []
        defs: list[Column] = []
        for cdef in schema.expressions:
            if not isinstance(cdef, exp.ColumnDef) or cdef.kind is None:
                continue
            col = cdef.name.upper()
            nullable = not any(isinstance(c.kind, exp.NotNullColumnConstraint) for c in cdef.constraints)
            collate = ""
            for c in cdef.constraints:
                if isinstance(c.kind, exp.CollateColumnConstraint) and "ci" in c.kind.sql().lower():
                    collate = " COLLATE NOCASE"
                    self._note("COLLATE 'en-ci' emulated with DuckDB NOCASE collation")
            defs.append(Column(col, cdef.kind.sql("snowflake").upper(), nullable))
            cols.append(f"{col} {_sf_type_to_duckdb(cdef.kind)}{collate}{'' if nullable else ' NOT NULL'}")
        self._note("Snowflake CLUSTER BY, IDENTITY/AUTOINCREMENT, declared constraints and DEFAULTs are "
                       "not executed; all rows are loaded with explicit values")
        return f"CREATE TABLE {name} ({', '.join(cols)})", TableDef(name, defs)

    def _pin_and_patch(self, node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.CurrentDate):
            return exp.cast(exp.Literal.string(self.as_of.isoformat()), "DATE")
        if isinstance(node, exp.CurrentTimestamp):
            return exp.cast(exp.Literal.string(f"{self.as_of.isoformat()} 00:00:00"), "TIMESTAMP")
        if isinstance(node, exp.ToChar) and node.args.get("format") is not None:
            self._note("TO_CHAR(number, format) emulated with thousands-separated fixed decimals")
            fmt = node.args["format"].name
            decimals = len(fmt.split(".")[1]) if "." in fmt else 0
            return exp.Anonymous(
                this="printf",
                expressions=[exp.Literal.string(f"%,.{decimals}f"), exp.cast(node.this, "DOUBLE")],
            )
        return node
