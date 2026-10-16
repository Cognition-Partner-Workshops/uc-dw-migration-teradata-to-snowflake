"""Column-level lineage for report views, computed independently on each side."""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage


def view_lineage(view_sql: str, dialect: str = "duckdb") -> dict[str, list[str]]:
    """Map each output column of ``CREATE VIEW ... AS <query>`` to its source ``TABLE.COLUMN`` set."""
    tree = sqlglot.parse_one(view_sql, read=dialect)
    query = tree.expression if isinstance(tree, exp.Create) else tree
    result: dict[str, list[str]] = {}
    for proj in query.selects:
        col = proj.alias_or_name
        try:
            node = lineage(col, query, dialect=dialect)
        except Exception:  # noqa: BLE001 - lineage is best-effort per column
            result[col.upper()] = ["<unresolved>"]
            continue
        sources: set[str] = set()
        for n in node.walk():
            if not n.downstream and isinstance(n.source, exp.Table):
                table = n.source.name.upper()
                schema = n.source.db.upper()
                column = n.name.split(".")[-1].upper()
                sources.add(f"{schema + '.' if schema else ''}{table}.{column}")
        result[col.upper()] = sorted(sources) or ["(derived: row count / constant)"]
    return result


def compare(legacy: dict[str, list[str]], target: dict[str, list[str]]) -> list[dict[str, object]]:
    rows = []
    for col in legacy:
        lsrc, tsrc = legacy.get(col, []), target.get(col)
        rows.append({"column": col, "legacy": lsrc, "target": tsrc or [],
                     "match": tsrc is not None and set(lsrc) == set(tsrc)})
    return rows
