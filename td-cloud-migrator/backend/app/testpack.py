"""Test pack: matching Teradata / target comparison queries per object, so a tester runs both and compares."""

from __future__ import annotations

import re

from .ddl_render import ident, q, target_schema
from .models import Conversion, SourceObject, TargetId, TdBaseType
from .routine_convert import parse_params

NUMERIC = {TdBaseType.BYTEINT, TdBaseType.SMALLINT, TdBaseType.INTEGER, TdBaseType.BIGINT}
NUMERIC |= {TdBaseType.DECIMAL, TdBaseType.NUMBER, TdBaseType.FLOAT}
TEXT = {TdBaseType.CHAR, TdBaseType.VARCHAR}
DATES = {TdBaseType.DATE, TdBaseType.TIMESTAMP, TdBaseType.TIMESTAMP_TZ}

Dialect = str  # "teradata" or a TargetId
NUM = {"teradata": "DECIMAL(38,4)", "bigquery": "BIGNUMERIC", "redshift": "DECIMAL(38,4)", "synapse": "DECIMAL(38,4)"}
STR = {"teradata": "VARCHAR(128)", "bigquery": "STRING", "redshift": "VARCHAR(128)", "synapse": "VARCHAR(128)"}


def _col(d: Dialect, name: str) -> str:
    return {"redshift": name.lower(), "synapse": f"[{name}]"}.get(d, name)


def _length(d: Dialect, c: str) -> str:
    return {
        "teradata": f"CHARACTER_LENGTH(TRIM(TRAILING FROM {c}))",
        "synapse": f"LEN({c})",
    }.get(d, f"LENGTH(RTRIM({c}))")


def _name(d: Dialect, obj: SourceObject, schema_map: dict[str, str], project: str) -> str:
    if d == "teradata":
        return f"{obj.database}.{obj.name}" if obj.database else obj.name
    schema = target_schema(obj.database, schema_map)
    parts = [project, schema] if d == "bigquery" else [schema]
    return q(d, *parts, ident(d, obj.name))


def _profile(d: Dialect, obj: SourceObject, fq: str) -> str:
    assert obj.table is not None
    metrics = [("row_count", "COUNT(*)")]
    for c in obj.table.columns:
        col = _col(d, c.name)
        metrics.append((f"nulls:{c.name}", f"COUNT(*) - COUNT({col})"))
        if c.base_type in NUMERIC:
            metrics.append((f"sum:{c.name}", f"SUM({col})"))
        elif c.base_type in TEXT:
            metrics.append((f"total_length:{c.name}", f"SUM({_length(d, col)})"))
        elif c.base_type in DATES:
            metrics.append((f"distinct:{c.name}", f"COUNT(DISTINCT {col})"))
    agg = ",\n       ".join(f"CAST({e} AS {NUM[d]}) AS m{i}" for i, (_, e) in enumerate(metrics))
    rows = "\nUNION ALL ".join(
        f"SELECT CAST('{obj.name}' AS {STR[d]}) AS object_name, CAST('{m}' AS {STR[d]}) AS metric, m{i} AS metric_value FROM s"
        for i, (m, _) in enumerate(metrics)
    )
    return f"WITH s AS (\n SELECT {agg}\n FROM {fq}\n)\n{rows}\nORDER BY 2;"


def _view(d: Dialect, fq: str) -> str:
    sample = f"SELECT TOP 20 * FROM {fq} ORDER BY 1;" if d in ("teradata", "synapse") else f"SELECT * FROM {fq} ORDER BY 1 LIMIT 20;"
    return f"SELECT COUNT(*) AS row_count FROM {fq};\n-- Sample rows (sorted by the first column; ties may differ):\n{sample}"


def _td_params(obj: SourceObject) -> list[str]:
    pat = (
        r"MACRO\s+[\w.\"]+\s*\((.*?)\)\s*AS\b"
        if obj.object_type == "macro"
        else r"PROCEDURE\s+[\w.\"]+\s*\((.*?)\)\s*(?:SQL\s+SECURITY\s+\w+\s*)?BEGIN\b"
    )
    m = re.search(pat, obj.sql, re.IGNORECASE | re.DOTALL)
    try:
        return [p.name for p in parse_params(m.group(1))] if m else []
    except ValueError:
        return []


def test_queries(obj: SourceObject, conv: Conversion, target: TargetId, schema_map: dict[str, str], project: str) -> tuple[str, str]:
    td, tg = _name("teradata", obj, schema_map, project), _name(target, obj, schema_map, project)
    if obj.object_type == "table" and obj.table:
        return _profile("teradata", obj, td), _profile(target, obj, tg)
    if obj.object_type == "view":
        return _view("teradata", td), _view(target, tg)
    usage = [ln.split(":", 1)[1].strip() for ln in conv.sql.splitlines() if re.match(r"--\s*(Usage|Run):", ln)]
    target_run = "\n".join(usage) or f"-- Run the converted {obj.object_type} with the same inputs as on Teradata."
    args = ", ".join(f"<{p}>" for p in _td_params(obj))
    if obj.object_type == "macro":
        source = f"EXEC {td}({args});"
    elif obj.object_type == "procedure":
        source = f"CALL {td}({args});"
    else:
        source = f"-- Run the original script: bteq < {obj.source_file}"
    note = "-- Use the same input values on both systems, then compare row counts, totals and the returned rows.\n"
    return note + source, note + target_run
