"""Shared Teradata-dictionary-driven SourceConnector logic (emulated and real issue the same DBC queries).

Subclasses only provide how to run a query (`_query`), stream a SELECT (`_stream`), and how to name a
table/column in SQL. All SQL here is valid on both Teradata and PostgreSQL; params use `?`.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator, Sequence
from typing import Any

import pyarrow as pa

from ...contracts.models import (
    ColumnMeta,
    ColumnProfile,
    ForeignKey,
    ProfileSpec,
    SourceTableSummary,
    TableMeta,
    TableProfile,
    TdBaseType,
)
from ...contracts.source import SourceConnector
from .catalog import (
    COLUMNSV_FIELDS,
    arrow_schema,
    column_from_dbc,
    fmt_number,
    indexes_from_dbc,
    keys_from_indexes,
    partition_columns,
    partition_expr_from_check,
    quote_ident,
    rows_to_batch,
    select_expr,
)

T = TdBaseType
NUMERIC_TYPES = {T.BYTEINT, T.SMALLINT, T.INTEGER, T.BIGINT, T.DECIMAL, T.NUMBER, T.FLOAT}
SYSTEM_DATABASES = {
    "DBC", "SYSLIB", "SYSUDTLIB", "SYSSPATIAL", "SYSBAR", "SYSJDBC", "SYSXML", "SYS_CALENDAR", "SYSADMIN",
    "SYSTEMFE", "TD_SYSFNLIB", "TD_SYSXML", "TDSTATS", "TDQCD", "TDMAPS", "TD_SERVER_DB", "TD_SYSGPL",
    "TDWM", "TDPUSER", "DBCMNGR", "LOCKLOGSHREDDER", "SQLJ", "EXTERNAL_AP", "CRASHDUMPS", "PUBLIC",
    "ALL", "DEFAULT", "TD_ANALYTICS_DB", "TDBCMGMT", "TD_METRIC_SVC",
}  # fmt: skip

_WHERE_DB = "UPPER(DatabaseName) = UPPER(?)"
_WHERE_TBL = f"{_WHERE_DB} AND UPPER(TableName) = UPPER(?)"
SQL_DATABASES = "SELECT DISTINCT DatabaseName FROM DBC.TablesV WHERE TableKind IN ('T', 'O')"
SQL_TABLES = (
    "SELECT DatabaseName, TableName, TableKind, CheckOpt, RequestText, CommentString FROM DBC.TablesV "
    "WHERE TableKind IN ('T', 'O') AND "
)
SQL_COLUMNS = (
    f"SELECT TableName, {', '.join(COLUMNSV_FIELDS)} FROM DBC.ColumnsV WHERE {_WHERE_TBL} ORDER BY ColumnId"
)
SQL_COLUMN_COUNTS = (
    f"SELECT TableName, COUNT(*) AS ColumnCount FROM DBC.ColumnsV WHERE {_WHERE_DB} GROUP BY TableName"
)
SQL_INDICES = (
    "SELECT IndexNumber, IndexType, UniqueFlag, IndexName, ColumnName, ColumnPosition FROM DBC.IndicesV "
    f"WHERE {_WHERE_TBL} ORDER BY IndexNumber, ColumnPosition"
)
SQL_PARTITIONING = f"SELECT ConstraintText FROM DBC.PartitioningConstraintsV WHERE {_WHERE_TBL}"
SQL_RI = (
    "SELECT IndexID, IndexName, ChildKeyColumn, ParentDB, ParentTable, ParentKeyColumn "
    "FROM DBC.All_RI_ChildrenV "
    "WHERE UPPER(ChildDB) = UPPER(?) AND UPPER(ChildTable) = UPPER(?) ORDER BY IndexID"
)
SQL_SIZES = (
    "SELECT TableName, SUM(CurrentPerm) AS CurrentPerm FROM DBC.TableSizeV "
    f"WHERE {_WHERE_DB} GROUP BY TableName"
)
SQL_ROWCOUNTS = (
    f"SELECT TableName, MAX(RowCount) AS RowCount FROM DBC.TableStatsV WHERE {_WHERE_DB} GROUP BY TableName"
)
SQL_VERSION = "SELECT InfoData FROM DBC.DBCInfoV WHERE InfoKey = 'VERSION'"


def _lower_keys(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k.lower(): v.strip() if isinstance(v, str) else v for k, v in r.items()} for r in rows]


class DictionarySource(SourceConnector):
    """Implements the SourceConnector contract on top of the DBC views."""

    optional_views_may_fail = False  # real Teradata: TableStatsV etc. may be missing / not granted

    @abstractmethod
    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Run a query; return rows as dicts (any key case)."""

    @abstractmethod
    def _stream(self, sql: str, batch_rows: int) -> Iterator[list[tuple]]:
        """Run a SELECT and yield lists of up to `batch_rows` row tuples (memory-bounded)."""

    @abstractmethod
    def _relation(self, database: str, table: str) -> str: ...

    def _column_ident(self, name: str) -> str:
        return quote_ident(name)

    def _ddl(self, database: str, table: str, request_text: str | None) -> str | None:
        return request_text

    def _rows(self, sql: str, params: Sequence[Any] = (), optional: bool = False) -> list[dict[str, Any]]:
        try:
            return _lower_keys(self._query(sql, params))
        except Exception:
            if optional and self.optional_views_may_fail:
                return []
            raise

    # -- metadata ---------------------------------------------------------------------------------
    def list_databases(self) -> list[str]:
        names = {r["databasename"] for r in self._rows(SQL_DATABASES)}
        return sorted(n for n in names if n.upper() not in SYSTEM_DATABASES)

    def list_tables(self, database: str) -> list[SourceTableSummary]:
        tables = self._rows(SQL_TABLES + _WHERE_DB + " ORDER BY TableName", [database])
        ncols = {r["tablename"]: int(r["columncount"]) for r in self._rows(SQL_COLUMN_COUNTS, [database])}
        sizes = {r["tablename"]: r["currentperm"] for r in self._rows(SQL_SIZES, [database], optional=True)}
        counts = {r["tablename"]: r["rowcount"] for r in self._rows(SQL_ROWCOUNTS, [database], optional=True)}
        return [
            SourceTableSummary(
                database=t["databasename"],
                name=t["tablename"],
                kind=_kind(t),
                row_count=_int(counts.get(t["tablename"])),
                size_bytes=_int(sizes.get(t["tablename"])),
                column_count=ncols.get(t["tablename"], 0),
            )
            for t in tables
        ]

    def _table_row(self, database: str, table: str) -> dict[str, Any]:
        rows = self._rows(SQL_TABLES + _WHERE_TBL, [database, table])
        if not rows:
            raise KeyError(f"table {database}.{table} not found")
        return rows[0]

    def columns(self, database: str, table: str) -> list[ColumnMeta]:
        rows = self._rows(SQL_COLUMNS, [database, table])
        if not rows:
            raise KeyError(f"table {database}.{table} not found")
        return [column_from_dbc(r) for r in rows]

    def describe_table(self, database: str, table: str) -> TableMeta:
        t = self._table_row(database, table)
        db, name = t["databasename"], t["tablename"]
        cols = self.columns(db, name)
        indexes = indexes_from_dbc(self._rows(SQL_INDICES, [db, name]))
        pi, pi_unique, unique_keys = keys_from_indexes(indexes)
        checks = self._rows(SQL_PARTITIONING, [db, name], optional=True)
        part = partition_expr_from_check(checks[0]["constrainttext"]) if checks else None
        fks: dict[int, ForeignKey] = {}
        for r in self._rows(SQL_RI, [db, name]):
            fk = fks.setdefault(
                int(r["indexid"]),
                ForeignKey(
                    columns=[], ref_database=r["parentdb"], ref_table=r["parenttable"], ref_columns=[]
                ),
            )
            fk.columns.append(r["childkeycolumn"])
            fk.ref_columns.append(r["parentkeycolumn"])
        sizes = {r["tablename"]: r["currentperm"] for r in self._rows(SQL_SIZES, [db], optional=True)}
        counts = {r["tablename"]: r["rowcount"] for r in self._rows(SQL_ROWCOUNTS, [db], optional=True)}
        return TableMeta(
            database=db,
            name=name,
            kind=_kind(t),
            columns=cols,
            primary_index=pi,
            primary_index_unique=pi_unique,
            partition_expression=part,
            partition_columns=partition_columns(part, [c.name for c in cols]),
            unique_keys=unique_keys,
            foreign_keys=list(fks.values()),
            row_count=_int(counts.get(name)),
            size_bytes=_int(sizes.get(name)),
            ddl=self._ddl(db, name, t.get("requesttext")),
        )

    # -- data -------------------------------------------------------------------------------------
    def _select_columns(self, database: str, table: str, columns: list[str] | None) -> list[ColumnMeta]:
        cols = self.columns(database, table)
        if not columns:
            return cols
        by_name = {c.name.lower(): c for c in cols}
        missing = [c for c in columns if c.lower() not in by_name]
        if missing:
            raise KeyError(f"unknown column(s) in {database}.{table}: {', '.join(missing)}")
        return [by_name[c.lower()] for c in columns]

    def extract(
        self, database: str, table: str, columns: list[str] | None = None, batch_rows: int = 100_000
    ) -> Iterator[pa.RecordBatch]:
        cols = self._select_columns(database, table, columns)
        schema = arrow_schema(cols)
        exprs = ", ".join(
            f"{select_expr(c, self._column_ident(c.name))} AS {quote_ident(c.name)}" for c in cols
        )
        sql = f"SELECT {exprs} FROM {self._relation(database, table)}"
        emitted = False
        for rows in self._stream(sql, max(1, batch_rows)):
            emitted = True
            yield rows_to_batch(schema, rows)
        if not emitted:
            yield rows_to_batch(schema, [])

    def profile(self, database: str, table: str, spec: ProfileSpec) -> TableProfile:
        all_cols = {c.name.lower(): c for c in self.columns(database, table)}
        numeric = [all_cols[c.lower()] for c in spec.numeric_columns if c.lower() in all_cols]
        numeric = [c for c in numeric if c.base_type in NUMERIC_TYPES]
        null_cols = list(
            dict.fromkeys([*(c.lower() for c in spec.null_columns), *(c.name.lower() for c in numeric)])
        )
        null_cols = [all_cols[c] for c in null_cols if c in all_cols]
        rel = self._relation(database, table)
        exprs = ["COUNT(*)"] + [f"COUNT(*) - COUNT({self._column_ident(c.name)})" for c in null_cols]
        for c in numeric:
            value = select_expr(c, self._column_ident(c.name))
            total = value if c.base_type == T.FLOAT else f"CAST({value} AS DECIMAL(38,{_sum_scale(c)}))"
            exprs += [f"SUM({total})", f"MIN({value})", f"MAX({value})"]
        sql = "SELECT " + ", ".join(f"{e} AS c{i}" for i, e in enumerate(exprs)) + f" FROM {rel}"
        row = list(self._rows(sql)[0].values())
        nulls = {c.name: int(v or 0) for c, v in zip(null_cols, row[1 : 1 + len(null_cols)], strict=True)}
        aggs = row[1 + len(null_cols) :]
        profiles = {c.name: ColumnProfile(column=c.name, null_count=nulls[c.name]) for c in null_cols}
        for i, c in enumerate(numeric):
            p = profiles[c.name]
            p.sum, p.min, p.max = (fmt_number(v) for v in aggs[3 * i : 3 * i + 3])
            if p.sum is None:
                p.sum = "0"
        dups = {}
        for key in spec.unique_keys:
            kc = ", ".join(self._column_ident(all_cols[k.lower()].name) for k in key)
            r = self._rows(
                f"SELECT COALESCE(SUM(cnt - 1), 0) AS dups FROM "
                f"(SELECT COUNT(*) AS cnt FROM {rel} GROUP BY {kc} HAVING COUNT(*) > 1) AS d"
            )
            dups[",".join(key)] = int(r[0]["dups"] or 0)
        checksum = self._checksum(database, table, [all_cols[c.lower()] for c in spec.checksum_columns])
        return TableProfile(
            row_count=int(row[0]),
            columns=list(profiles.values()),
            checksum=checksum,
            duplicate_key_count=dups,
        )

    def _checksum(self, database: str, table: str, columns: list[ColumnMeta]) -> str | None:
        """Canonical checksum (contracts/checksum.py) computed in the source engine, if supported."""
        return None


def _sum_scale(c: ColumnMeta) -> int:
    if c.base_type == T.DECIMAL:
        return c.scale or 0
    if c.base_type == T.NUMBER:
        return 15 if c.scale is None else c.scale
    return 0


def _kind(row: dict[str, Any]) -> str:
    return "SET" if (row.get("checkopt") or "N") == "Y" else "MULTISET"


def _int(v: Any) -> int | None:
    return None if v is None else int(v)
