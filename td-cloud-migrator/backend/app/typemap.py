"""Teradata -> BigQuery / Redshift / Synapse column type rules."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ColumnMeta, TargetId, TdBaseType

T = TdBaseType


@dataclass(frozen=True, slots=True)
class MappedType:
    type: str
    lossy: bool = False
    note: str | None = None


def _bigquery(c: ColumnMeta) -> MappedType:
    b = c.base_type
    if b in (T.BYTEINT, T.SMALLINT, T.INTEGER, T.BIGINT):
        return MappedType("INT64", note=None if b == T.BIGINT else "Widened to INT64 (only integer type)")
    if b in (T.DECIMAL, T.NUMBER):
        p, s = c.precision, c.scale
        if p is None:
            return MappedType("BIGNUMERIC", True, "Unbounded NUMBER -> BIGNUMERIC (floating decimal)")
        s = s or 0
        if s <= 9 and p - s <= 29:
            return MappedType(f"NUMERIC({p},{s})")
        return MappedType(f"BIGNUMERIC({p},{s})", note="Exceeds NUMERIC range -> BIGNUMERIC")
    if b == T.FLOAT:
        return MappedType("FLOAT64")
    if b == T.CHAR:
        return MappedType(f"STRING({c.length})", note="No fixed-width CHAR; values are not blank-padded")
    if b == T.VARCHAR:
        return MappedType(f"STRING({c.length})")
    if b == T.CLOB:
        return MappedType("STRING")
    if b in (T.BYTE, T.VARBYTE):
        return MappedType(f"BYTES({c.length})")
    if b == T.BLOB:
        return MappedType("BYTES")
    if b == T.DATE:
        return MappedType("DATE")
    if b == T.TIME:
        return MappedType("TIME")
    if b == T.TIMESTAMP:
        return MappedType("DATETIME", note="Teradata TIMESTAMP has no zone -> DATETIME")
    if b == T.TIMESTAMP_TZ:
        return MappedType("TIMESTAMP", True, "Normalised to UTC; original offset is not kept")
    if b == T.TIME_TZ:
        return MappedType("TIME", True, "Time zone offset dropped")
    if b == T.JSON:
        return MappedType("JSON")
    return MappedType("STRING", True, f"No {b.value} type; stored as text")


def _redshift(c: ColumnMeta) -> MappedType:
    b = c.base_type
    if b == T.BYTEINT:
        return MappedType("SMALLINT", note="No 1-byte integer -> SMALLINT")
    if b in (T.SMALLINT, T.INTEGER, T.BIGINT):
        return MappedType(b.value)
    if b in (T.DECIMAL, T.NUMBER):
        if c.precision is None:
            return MappedType("DECIMAL(38,15)", True, "Unbounded NUMBER -> DECIMAL(38,15)")
        return MappedType(f"DECIMAL({c.precision},{c.scale or 0})")
    if b == T.FLOAT:
        return MappedType("DOUBLE PRECISION")
    if b in (T.CHAR, T.VARCHAR):
        n = c.length or 1
        if c.charset == "UNICODE":
            return MappedType(f"VARCHAR({min(n * 4, 65535)})", note="UNICODE: length x4 (Redshift sizes are bytes)")
        return MappedType(f"{b.value}({n})")
    if b == T.CLOB:
        return MappedType("VARCHAR(65535)", True, "CLOB truncated to 65535 bytes")
    if b in (T.BYTE, T.VARBYTE):
        return MappedType(f"VARBYTE({c.length})")
    if b == T.BLOB:
        return MappedType("VARBYTE(1024000)", True, "BLOB capped at 1 MB")
    if b == T.DATE:
        return MappedType("DATE")
    if b == T.TIME:
        return MappedType("TIME")
    if b == T.TIME_TZ:
        return MappedType("TIMETZ")
    if b == T.TIMESTAMP:
        return MappedType("TIMESTAMP")
    if b == T.TIMESTAMP_TZ:
        return MappedType("TIMESTAMPTZ")
    if b == T.JSON:
        return MappedType("SUPER", note="JSON -> SUPER (use JSON_PARSE on load)")
    return MappedType("VARCHAR(65535)", True, f"No {b.value} type; stored as text")


def _synapse(c: ColumnMeta) -> MappedType:
    b = c.base_type
    if b == T.BYTEINT:
        return MappedType("SMALLINT", note="TINYINT is unsigned -> SMALLINT")
    if b in (T.SMALLINT, T.BIGINT):
        return MappedType(b.value)
    if b == T.INTEGER:
        return MappedType("INT")
    if b in (T.DECIMAL, T.NUMBER):
        if c.precision is None:
            return MappedType("DECIMAL(38,15)", True, "Unbounded NUMBER -> DECIMAL(38,15)")
        return MappedType(f"DECIMAL({c.precision},{c.scale or 0})")
    if b == T.FLOAT:
        return MappedType("FLOAT")
    if b in (T.CHAR, T.VARCHAR):
        uni, n = c.charset == "UNICODE", c.length or 1
        limit = 4000 if uni else 8000
        name = ("N" if uni else "") + b.value
        return MappedType(f"{name}({n if n <= limit else 'MAX'})")
    if b == T.CLOB:
        return MappedType("NVARCHAR(MAX)" if c.charset == "UNICODE" else "VARCHAR(MAX)")
    if b == T.BYTE:
        return MappedType(f"BINARY({c.length})")
    if b == T.VARBYTE:
        return MappedType(f"VARBINARY({c.length if (c.length or 0) <= 8000 else 'MAX'})")
    if b == T.BLOB:
        return MappedType("VARBINARY(MAX)")
    if b == T.DATE:
        return MappedType("DATE")
    if b == T.TIME:
        return MappedType(f"TIME({c.fractional_seconds if c.fractional_seconds is not None else 6})")
    if b == T.TIMESTAMP:
        fs = c.fractional_seconds if c.fractional_seconds is not None else 6
        return MappedType(f"DATETIME2({fs})")
    if b == T.TIMESTAMP_TZ:
        return MappedType(f"DATETIMEOFFSET({c.fractional_seconds or 6})")
    if b == T.TIME_TZ:
        return MappedType("TIME", True, "Time zone offset dropped")
    if b == T.JSON:
        return MappedType("NVARCHAR(MAX)", note="JSON stored as text; query with OPENJSON / JSON_VALUE")
    return MappedType("NVARCHAR(4000)", True, f"No {b.value} type; stored as text")


_RULES = {"bigquery": _bigquery, "redshift": _redshift, "synapse": _synapse}


def map_type(col: ColumnMeta, target: TargetId) -> MappedType:
    return _RULES[target](col)


def duckdb_type(col: ColumnMeta) -> str:
    """Type used by the local DuckDB warehouse simulator."""
    b = col.base_type
    if b in (T.BYTEINT, T.SMALLINT):
        return "SMALLINT"
    if b == T.INTEGER:
        return "INTEGER"
    if b == T.BIGINT:
        return "BIGINT"
    if b in (T.DECIMAL, T.NUMBER):
        if col.precision is None:
            return "DECIMAL(38,15)"
        return f"DECIMAL({min(col.precision, 38)},{col.scale or 0})"
    if b == T.FLOAT:
        return "DOUBLE"
    if b in (T.BYTE, T.VARBYTE, T.BLOB):
        return "BLOB"
    if b == T.DATE:
        return "DATE"
    if b in (T.TIME, T.TIME_TZ):
        return "TIME"
    if b == T.TIMESTAMP:
        return "TIMESTAMP"
    if b == T.TIMESTAMP_TZ:
        return "TIMESTAMPTZ"
    return "VARCHAR"
