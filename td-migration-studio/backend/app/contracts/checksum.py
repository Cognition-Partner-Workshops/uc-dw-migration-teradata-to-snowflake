"""Canonical, order-independent table checksum used for source/staged vs target reconciliation.

Definition (every engine must implement exactly this):
  canon(v) per value, by type:
    NULL                    -> '\\N'
    integers                -> base-10 text ('-12')
    decimal(p,s)            -> fixed-scale text with exactly s decimals ('58.90'); no exponent
    float/double            -> round(v * 1e6) as base-10 integer text ('-23545621')
    string                  -> the string as-is (CHAR already right-trimmed)
    date                    -> 'YYYY-MM-DD'
    timestamp (naive)       -> 'YYYY-MM-DD HH:MM:SS.ffffff'
    timestamp with tz       -> converted to UTC, then as timestamp (naive)
    bool                    -> 'true' / 'false'
    binary                  -> lowercase hex
  row_string  = canon(c1) || chr(31) || canon(c2) || ... (columns in plan order)
  row_hash    = first 8 hex chars of md5(row_string) interpreted as unsigned 32-bit int
  checksum    = SUM(row_hash) over all rows, as base-10 text (fits in int64 for < 2^31 rows)

Per-target SQL renderings live in targets_meta/<id>.yaml (dq.checksum_sql_template).
This module is the DuckDB reference, used for staged Parquet and by simulated targets.
"""

from __future__ import annotations

import pyarrow as pa

SEP = "chr(31)"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def canonical_expr_duckdb(column: str, arrow_type: pa.DataType) -> str:
    c = _q(column)
    t = arrow_type
    if pa.types.is_integer(t) or pa.types.is_decimal(t):
        expr = f"CAST({c} AS VARCHAR)"
    elif pa.types.is_floating(t):
        expr = f"CAST(CAST(ROUND(CAST({c} AS DOUBLE) * 1e6) AS BIGINT) AS VARCHAR)"
    elif pa.types.is_date(t):
        expr = f"strftime({c}, '%Y-%m-%d')"
    elif pa.types.is_timestamp(t):
        if t.tz:
            expr = f"strftime(({c}) AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S.%f')"
        else:
            expr = f"strftime({c}, '%Y-%m-%d %H:%M:%S.%f')"
    elif pa.types.is_boolean(t):
        expr = f"CASE WHEN {c} THEN 'true' ELSE 'false' END"
    elif pa.types.is_binary(t) or pa.types.is_large_binary(t):
        expr = f"lower(hex({c}))"
    else:
        expr = f"CAST({c} AS VARCHAR)"
    return f"COALESCE({expr}, '\\N')"


def duckdb_checksum_sql(relation: str, schema: pa.Schema, columns: list[str] | None = None) -> str:
    """SELECT returning (row_count, checksum) for `relation` (a table name or read_parquet(...))."""
    cols = columns or schema.names
    parts = f" || {SEP} || ".join(canonical_expr_duckdb(c, schema.field(c).type) for c in cols)
    row_hash = f"CAST(('0x' || substr(md5({parts}), 1, 8)) AS BIGINT)"
    return (
        f"SELECT COUNT(*) AS row_count, CAST(COALESCE(SUM({row_hash}), 0) AS VARCHAR) AS checksum "
        f"FROM {relation}"
    )
