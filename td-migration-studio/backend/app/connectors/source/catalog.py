"""Teradata data-dictionary <-> TableMeta mapping shared by the emulated and real source connectors.

Both connectors read DBC.ColumnsV / DBC.IndicesV / ... rows and turn them into identical `ColumnMeta` /
`TableMeta` objects through this module; the seeder uses the inverse (`column_to_dbc`) to fill the
emulated dictionary from parsed DDL. Also holds the Arrow type contract and the extract SELECT list.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pyarrow as pa

from ...contracts.models import ColumnMeta, TdBaseType

T = TdBaseType

# DBC.ColumnsV.ColumnType codes (INTERVAL/PERIOD codes carry the qualifier).
SIMPLE_CODES: dict[TdBaseType, str] = {
    T.BYTEINT: "I1", T.SMALLINT: "I2", T.INTEGER: "I", T.BIGINT: "I8", T.DECIMAL: "D", T.NUMBER: "N",
    T.FLOAT: "F", T.CHAR: "CF", T.VARCHAR: "CV", T.CLOB: "CO", T.BYTE: "BF", T.VARBYTE: "BV", T.BLOB: "BO",
    T.DATE: "DA", T.TIME: "AT", T.TIME_TZ: "TZ", T.TIMESTAMP: "TS", T.TIMESTAMP_TZ: "SZ", T.JSON: "JN",
    T.XML: "XM",
}  # fmt: skip
INTERVAL_CODES: dict[str, str] = {
    "YEAR": "YR", "YEAR TO MONTH": "YM", "MONTH": "MO", "DAY": "DY", "DAY TO HOUR": "DH",
    "DAY TO MINUTE": "DM", "DAY TO SECOND": "DS", "HOUR": "HR", "HOUR TO MINUTE": "HM",
    "HOUR TO SECOND": "HS", "MINUTE": "MI", "MINUTE TO SECOND": "MS", "SECOND": "SC",
}  # fmt: skip
PERIOD_CODES: dict[str, str] = {
    "DATE": "PD", "TIME": "PT", "TIME WITH TIME ZONE": "PZ", "TIMESTAMP": "PS",
    "TIMESTAMP WITH TIME ZONE": "PM",
}  # fmt: skip
CODE_TO_BASE: dict[str, TdBaseType] = {v: k for k, v in SIMPLE_CODES.items()}
CODE_TO_BASE.update({c: T.INTERVAL for c in INTERVAL_CODES.values()})
CODE_TO_BASE.update({c: T.PERIOD for c in PERIOD_CODES.values()})
_INTERVAL_BY_CODE = {v: k for k, v in INTERVAL_CODES.items()}
_PERIOD_BY_CODE = {v: k for k, v in PERIOD_CODES.items()}

CHAR_TYPES = {T.CHAR, T.VARCHAR, T.CLOB}
UNBOUNDED = -128  # DecimalTotalDigits/DecimalFractionalDigits value for NUMBER / NUMBER(*)
UNBOUNDED_NUMBER = (38, 15)  # Arrow decimal used for unbounded NUMBER (contract)
CHARSET_CODES = {"LATIN": 1, "UNICODE": 2}
_FIXED_BYTES = {T.BYTEINT: 1, T.SMALLINT: 2, T.INTEGER: 4, T.BIGINT: 8, T.FLOAT: 8, T.DATE: 4, T.NUMBER: 18}


def type_code(col: ColumnMeta) -> str:
    if col.base_type == T.INTERVAL:
        return INTERVAL_CODES[col.interval_qualifier or "DAY"]
    if col.base_type == T.PERIOD:
        return PERIOD_CODES[col.interval_qualifier or "DATE"]
    return SIMPLE_CODES[col.base_type]


def type_text(col: ColumnMeta) -> str:
    """Canonical Teradata type text, e.g. 'VARCHAR(60) CHARACTER SET UNICODE'."""
    b, fs = col.base_type, col.fractional_seconds
    if b in CHAR_TYPES:
        return f"{b.value}({col.length}) CHARACTER SET {col.charset or 'LATIN'}"
    if b in (T.BYTE, T.VARBYTE, T.BLOB):
        return f"{b.value}({col.length})"
    if b == T.DECIMAL:
        return f"DECIMAL({col.precision},{col.scale})"
    if b == T.NUMBER:
        if col.precision is None:
            return "NUMBER" if col.scale is None else f"NUMBER(*,{col.scale})"
        return f"NUMBER({col.precision},{col.scale or 0})"
    if b in (T.TIME, T.TIMESTAMP):
        return f"{b.value}({fs})"
    if b in (T.TIME_TZ, T.TIMESTAMP_TZ):
        return f"{b.value[:-3]}({fs}) WITH TIME ZONE"
    if b == T.INTERVAL:
        q = (col.interval_qualifier or "DAY").split(" TO ")
        lead = f"{q[0]}({col.precision})" if q[0] != "SECOND" else f"SECOND({col.precision},{fs})"
        if len(q) == 1:
            return f"INTERVAL {lead}"
        return f"INTERVAL {lead} TO {q[1]}" + (f"({fs})" if q[1] == "SECOND" else "")
    if b == T.PERIOD:
        q = col.interval_qualifier or "DATE"
        if q == "DATE":
            return "PERIOD(DATE)"
        head, _, tail = q.partition(" ")
        return f"PERIOD({head}({fs}){' ' + tail if tail else ''})"
    return b.value


def finalize(col: ColumnMeta) -> ColumnMeta:
    """Fill td_type / td_type_code from the structured fields."""
    col.td_type_code = type_code(col)
    col.td_type = type_text(col)
    return col


def column_length_bytes(col: ColumnMeta) -> int:
    b = col.base_type
    if b in CHAR_TYPES:
        return (col.length or 0) * (2 if col.charset == "UNICODE" else 1)
    if b in (T.BYTE, T.VARBYTE, T.BLOB):
        return col.length or 0
    if b == T.DECIMAL:
        p = col.precision or 0
        return 1 if p <= 2 else 2 if p <= 4 else 4 if p <= 9 else 8 if p <= 18 else 16
    if b in (T.TIMESTAMP, T.TIMESTAMP_TZ):
        return 12 if b == T.TIMESTAMP_TZ else 10
    if b in (T.TIME, T.TIME_TZ):
        return 8 if b == T.TIME_TZ else 6
    return _FIXED_BYTES.get(b, 8)


# --------------------------------------------------------------------------------------------------
# DBC.ColumnsV rows
# --------------------------------------------------------------------------------------------------

COLUMNSV_FIELDS = (
    "ColumnName", "ColumnId", "ColumnType", "ColumnLength", "DecimalTotalDigits", "DecimalFractionalDigits",
    "CharType", "UpperCaseFlag", "Nullable", "DefaultValue", "Compressible", "CompressValueList",
    "ColumnFormat", "CommentString",
)  # fmt: skip
FIRST_COLUMN_ID = 1025  # Teradata numbers columns from 1025


def _quote_lit(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def render_compress_list(col: ColumnMeta) -> str | None:
    if not col.compress_values:
        return None
    numeric = col.base_type in (T.BYTEINT, T.SMALLINT, T.INTEGER, T.BIGINT, T.DECIMAL, T.NUMBER, T.FLOAT)
    return "(" + ",".join(v if numeric else _quote_lit(v) for v in col.compress_values) + ")"


def parse_compress_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
        for m in re.finditer(r"'((?:[^']|'')*)'|([^\s,()']+)", text)
    ]


def column_to_dbc(col: ColumnMeta) -> dict[str, Any]:
    """ColumnMeta -> DBC.ColumnsV row (Teradata column names)."""
    b = col.base_type
    if b == T.NUMBER:
        total = UNBOUNDED if col.precision is None else col.precision
        frac = UNBOUNDED if col.scale is None else col.scale
    elif b in (T.DECIMAL, T.INTERVAL):
        total, frac = col.precision, col.scale if b == T.DECIMAL else col.fractional_seconds
    elif b in (T.TIME, T.TIME_TZ, T.TIMESTAMP, T.TIMESTAMP_TZ, T.PERIOD):
        total, frac = None, col.fractional_seconds
    else:
        total = frac = None
    is_char = b in CHAR_TYPES
    return {
        "ColumnName": col.name,
        "ColumnId": FIRST_COLUMN_ID + col.ordinal - 1,
        "ColumnType": type_code(col),
        "ColumnLength": column_length_bytes(col),
        "DecimalTotalDigits": total,
        "DecimalFractionalDigits": frac,
        "CharType": CHARSET_CODES.get(col.charset or "LATIN", 1) if is_char else 0,
        "UpperCaseFlag": ("C" if col.case_specific else "N") if is_char else None,
        "Nullable": "Y" if col.nullable else "N",
        "DefaultValue": col.default,
        "Compressible": "C" if col.compress_values is not None else "N",
        "CompressValueList": render_compress_list(col),
        "ColumnFormat": col.format,
        "CommentString": col.comment,
    }


def _s(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def column_from_dbc(row: dict[str, Any]) -> ColumnMeta:
    """DBC.ColumnsV row (keys case-insensitive, CHAR padding tolerated) -> ColumnMeta."""
    r = {k.lower(): _s(v) for k, v in row.items()}
    code = r["columntype"]
    base = CODE_TO_BASE[code]
    total, frac = r.get("decimaltotaldigits"), r.get("decimalfractionaldigits")
    total = None if total is None else int(total)
    frac = None if frac is None else int(frac)
    col = ColumnMeta(
        name=r["columnname"],
        ordinal=int(r["columnid"]) - FIRST_COLUMN_ID + 1,
        base_type=base,
        td_type="",
        td_type_code=code,
        nullable=r.get("nullable") != "N",
        default=r.get("defaultvalue"),
        format=r.get("columnformat"),
        comment=r.get("commentstring"),
    )
    if base in CHAR_TYPES:
        ct = int(r.get("chartype") or 1)
        col.charset = "UNICODE" if ct == 2 else "LATIN" if ct == 1 else None
        col.length = int(r["columnlength"]) // (2 if ct == 2 else 1)
        col.case_specific = r.get("uppercaseflag") == "C"
    elif base in (T.BYTE, T.VARBYTE, T.BLOB):
        col.length = int(r["columnlength"])
    elif base == T.DECIMAL:
        col.precision, col.scale = total, frac
    elif base == T.NUMBER:
        col.precision = None if total in (None, UNBOUNDED) else total
        col.scale = None if frac in (None, UNBOUNDED) else frac
    elif base in (T.TIME, T.TIME_TZ, T.TIMESTAMP, T.TIMESTAMP_TZ):
        col.fractional_seconds = frac
    elif base == T.INTERVAL:
        col.interval_qualifier, col.precision = _INTERVAL_BY_CODE[code], total
        col.fractional_seconds = frac if "SECOND" in col.interval_qualifier else None
    elif base == T.PERIOD:
        col.interval_qualifier = _PERIOD_BY_CODE[code]
        col.fractional_seconds = None if code == "PD" else frac
    if r.get("compressible") == "C":
        col.compress_values = parse_compress_list(r.get("compressvaluelist"))
    return finalize(col)


# --------------------------------------------------------------------------------------------------
# Indexes / partitioning (DBC.IndicesV, DBC.PartitioningConstraintsV)
# --------------------------------------------------------------------------------------------------


@dataclass
class IndexDef:
    number: int  # IndexNumber: 1 = primary index, secondary indexes 4, 8, 12, ...
    kind: str  # IndexType: P (PI), Q (partitioned PI), S (secondary), K (primary key), U (unique constraint)
    unique: bool
    columns: list[str] = field(default_factory=list)
    name: str | None = None


def indexes_from_dbc(rows: Iterable[dict[str, Any]]) -> list[IndexDef]:
    out: dict[int, IndexDef] = {}
    for row in sorted(
        ({k.lower(): _s(v) for k, v in r.items()} for r in rows),
        key=lambda r: (int(r["indexnumber"]), int(r["columnposition"])),
    ):
        idx = out.setdefault(
            int(row["indexnumber"]),
            IndexDef(
                int(row["indexnumber"]), row["indextype"], row["uniqueflag"] == "Y", [], row["indexname"]
            ),
        )
        idx.columns.append(row["columnname"])
    return list(out.values())


def keys_from_indexes(indexes: Sequence[IndexDef]) -> tuple[list[str], bool, list[list[str]]]:
    """-> (primary_index, primary_index_unique, unique_keys) in Teradata precedence order."""
    pi = next((i for i in indexes if i.kind in ("P", "Q")), None)
    keys: list[list[str]] = []
    for i in sorted(indexes, key=lambda i: i.number):
        if i.unique and i.columns not in keys:
            keys.append(list(i.columns))
    return (list(pi.columns) if pi else []), bool(pi and pi.unique), keys


def partition_check_text(expr: str, max_partitions: int = 65535) -> str:
    """DBC.PartitioningConstraintsV.ConstraintText for a PARTITION BY expression."""
    return f"CHECK (({expr}) BETWEEN 1 AND {max_partitions})"


def partition_expr_from_check(text: str | None) -> str | None:
    if not text:
        return None
    m = re.match(r"\s*CHECK\s*\(\s*\((.*)\)\s*BETWEEN\s+\d+\s+AND\s+\d+\s*\)\s*$", text, re.S | re.I)
    return m.group(1).strip() if m else text.strip()


def partition_columns(expr: str | None, column_names: Sequence[str]) -> list[str]:
    """Columns referenced by a partitioning expression, in order of first appearance."""
    if not expr:
        return []
    stripped = re.sub(r"'(?:[^']|'')*'", "''", expr)
    hits = []
    for c in column_names:
        m = re.search(rf'(?<![\w$#"]){re.escape(c)}(?![\w$#])|"{re.escape(c)}"', stripped, re.I)
        if m:
            hits.append((m.start(), c))
    return [c for _, c in sorted(hits)]


# --------------------------------------------------------------------------------------------------
# Arrow contract + extract
# --------------------------------------------------------------------------------------------------

_ARROW_SIMPLE: dict[TdBaseType, pa.DataType] = {
    T.BYTEINT: pa.int8(), T.SMALLINT: pa.int16(), T.INTEGER: pa.int32(), T.BIGINT: pa.int64(),
    T.FLOAT: pa.float64(), T.DATE: pa.date32(), T.TIME: pa.time64("us"), T.TIMESTAMP: pa.timestamp("us"),
    T.TIMESTAMP_TZ: pa.timestamp("us", tz="UTC"), T.BYTE: pa.binary(), T.VARBYTE: pa.binary(),
    T.BLOB: pa.binary(),
}  # fmt: skip


def arrow_type(col: ColumnMeta) -> pa.DataType:
    if col.base_type == T.DECIMAL:
        return pa.decimal128(col.precision or 18, col.scale or 0)
    if col.base_type == T.NUMBER:
        if col.precision is None:
            return pa.decimal128(UNBOUNDED_NUMBER[0], UNBOUNDED_NUMBER[1] if col.scale is None else col.scale)
        return pa.decimal128(col.precision, col.scale or 0)
    return _ARROW_SIMPLE.get(col.base_type, pa.string())


def arrow_schema(columns: Sequence[ColumnMeta]) -> pa.Schema:
    return pa.schema([pa.field(c.name, arrow_type(c), nullable=c.nullable) for c in columns])


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def select_expr(col: ColumnMeta, ident: str | None = None) -> str:
    """SELECT-list expression (valid in Teradata and PostgreSQL) yielding values for the Arrow contract."""
    c = ident or quote_ident(col.name)
    t = arrow_type(col)
    if col.base_type == T.CHAR:
        return f"TRIM(TRAILING FROM {c})"
    if col.base_type == T.NUMBER:
        return f"CAST({c} AS DECIMAL({t.precision},{t.scale}))"
    if col.base_type in (T.INTERVAL, T.PERIOD, T.TIME_TZ, T.JSON, T.XML):
        return f"CAST({c} AS VARCHAR(2000))"
    return c


def _to_utc(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    return v


def rows_to_batch(schema: pa.Schema, rows: Sequence[Sequence[Any]]) -> pa.RecordBatch:
    cols = list(zip(*rows, strict=True)) if rows else [()] * len(schema)
    arrays = []
    for f, values in zip(schema, cols, strict=True):
        if pa.types.is_timestamp(f.type) and f.type.tz:
            values = [_to_utc(v) for v in values]
        elif pa.types.is_string(f.type):
            values = [v if v is None or isinstance(v, str) else str(v) for v in values]
        arrays.append(pa.array(values, type=f.type))
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def fmt_number(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float):
        return repr(v)
    return format(v, "f") if not isinstance(v, int) else str(v)
