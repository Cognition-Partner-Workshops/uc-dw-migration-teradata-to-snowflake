"""Parse the Arrow type strings used by `TargetTypeInfo.arrow_type` (e.g. 'decimal128(38, 9)')."""

from __future__ import annotations

import re
from functools import lru_cache

import pyarrow as pa

_DECIMAL = re.compile(r"^decimal(128|256)?\(\s*(\d+)\s*,\s*(\d+)\s*\)$")
_TS = re.compile(r"^timestamp\[(s|ms|us|ns)(?:\s*,\s*tz\s*=\s*([^\]]+))?\]$")
_ALIASES = {
    "str": "string",
    "text": "string",
    "boolean": "bool",
    "date": "date32",
    "timestamp": "timestamp[us]",
}


@lru_cache(maxsize=512)
def parse_arrow_type(spec: str) -> pa.DataType:
    s = spec.strip()
    s = _ALIASES.get(s.lower(), s)
    if m := _DECIMAL.match(s):
        width, p, sc = m.group(1), int(m.group(2)), int(m.group(3))
        return (pa.decimal256 if width == "256" or p > 38 else pa.decimal128)(p, sc)
    if m := _TS.match(s):
        tz = m.group(2).strip().strip("'\"") if m.group(2) else None
        return pa.timestamp(m.group(1), tz=tz)
    try:
        return pa.type_for_alias(s)
    except ValueError as exc:
        raise ValueError(f"unsupported arrow type string '{spec}'") from exc


def is_numeric(t: pa.DataType) -> bool:
    return pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_decimal(t)


def is_text(t: pa.DataType) -> bool:
    return pa.types.is_string(t) or pa.types.is_large_string(t)
