"""Teradata type text, DBC dictionary codes and index helpers shared by the DDL and DBC-export parsers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import ColumnMeta, TdBaseType

T = TdBaseType

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
INTEGER_TYPES = {T.BYTEINT, T.SMALLINT, T.INTEGER, T.BIGINT}
NUMERIC_TYPES = INTEGER_TYPES | {T.DECIMAL, T.NUMBER, T.FLOAT}
UNBOUNDED = -128
FIRST_COLUMN_ID = 1025


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
        return f"INTERVAL {col.interval_qualifier or 'DAY'}"
    if b == T.PERIOD:
        return f"PERIOD({col.interval_qualifier or 'DATE'})"
    return b.value


def finalize(col: ColumnMeta) -> ColumnMeta:
    col.td_type_code = type_code(col)
    col.td_type = type_text(col)
    return col


def parse_compress_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2) for m in re.finditer(r"'((?:[^']|'')*)'|([^\s,()']+)", text)
    ]


def _s(v: Any) -> Any:
    v = v.strip() if isinstance(v, str) else v
    return None if v == "" else v


def _int(v: Any) -> int | None:
    v = _s(v)
    return None if v is None else int(float(v))


def column_from_dbc(row: dict[str, Any]) -> ColumnMeta:
    """DBC.ColumnsV row (keys case-insensitive) -> ColumnMeta."""
    r = {k.lower(): _s(v) for k, v in row.items()}
    code = (r.get("columntype") or "").upper()
    if code not in CODE_TO_BASE:
        raise ValueError(f"unknown DBC ColumnType {code!r} for column {r.get('columnname')}")
    base = CODE_TO_BASE[code]
    total, frac = _int(r.get("decimaltotaldigits")), _int(r.get("decimalfractionaldigits"))
    col_id = _int(r.get("columnid")) or FIRST_COLUMN_ID
    col = ColumnMeta(
        name=r["columnname"],
        ordinal=col_id - FIRST_COLUMN_ID + 1 if col_id >= FIRST_COLUMN_ID else col_id,
        base_type=base,
        td_type_code=code,
        nullable=(r.get("nullable") or "Y").upper() != "N",
        default=r.get("defaultvalue"),
        format=r.get("columnformat"),
        comment=r.get("commentstring"),
    )
    if base in CHAR_TYPES:
        ct = _int(r.get("chartype")) or 1
        col.charset = "UNICODE" if ct == 2 else "LATIN"
        col.length = (_int(r.get("columnlength")) or 1) // (2 if ct == 2 else 1)
        col.case_specific = (r.get("uppercaseflag") or "N").upper() == "C"
    elif base in (T.BYTE, T.VARBYTE, T.BLOB):
        col.length = _int(r.get("columnlength"))
    elif base == T.DECIMAL:
        col.precision, col.scale = total, frac or 0
    elif base == T.NUMBER:
        col.precision = None if total in (None, UNBOUNDED) else total
        col.scale = None if frac in (None, UNBOUNDED) else frac
    elif base in (T.TIME, T.TIME_TZ, T.TIMESTAMP, T.TIMESTAMP_TZ):
        col.fractional_seconds = 6 if frac is None else frac
    elif base == T.INTERVAL:
        col.interval_qualifier, col.precision = _INTERVAL_BY_CODE[code], total
    elif base == T.PERIOD:
        col.interval_qualifier = _PERIOD_BY_CODE[code]
    if (r.get("compressible") or "N").upper() == "C":
        col.compress_values = parse_compress_list(r.get("compressvaluelist"))
    if (r.get("idcoltype") or "").upper() in ("GA", "GD"):
        from .models import Identity

        col.identity = Identity(always=r["idcoltype"].upper() == "GA")
    return finalize(col)


@dataclass
class IndexDef:
    number: int  # 1 = primary index, secondary indexes 4, 8, 12, ...
    kind: str  # P (PI), Q (partitioned PI), S (secondary), K (primary key), U (unique constraint)
    unique: bool
    columns: list[str] = field(default_factory=list)
    name: str | None = None


def keys_from_indexes(indexes: Sequence[IndexDef]) -> tuple[list[str], bool, list[list[str]]]:
    """-> (primary_index, primary_index_unique, unique_keys) in Teradata precedence order."""
    pi = next((i for i in indexes if i.kind in ("P", "Q")), None)
    keys: list[list[str]] = []
    for i in sorted(indexes, key=lambda i: i.number):
        if i.unique and i.columns not in keys:
            keys.append(list(i.columns))
    return (list(pi.columns) if pi else []), bool(pi and pi.unique), keys


def partition_columns(expr: str | None, column_names: Sequence[str]) -> list[str]:
    """Columns referenced by a partitioning expression, in order of first appearance."""
    if not expr:
        return []
    stripped = re.sub(r"'(?:[^']|'')*'", "''", expr)
    hits = []
    for c in column_names:
        m = re.search(rf'(?<![\w$#"]){re.escape(c)}(?![\w$#])|"{re.escape(c)}"', stripped, re.IGNORECASE)
        if m:
            hits.append((m.start(), c))
    return [c for _, c in sorted(hits)]
