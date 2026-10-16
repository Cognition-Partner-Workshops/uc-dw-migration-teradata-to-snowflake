"""Declared-type conformance between the Teradata and converted Snowflake DDL."""

from __future__ import annotations

import re

from .engines import TableDef

_INT_RANK = {"BYTEINT": 1, "TINYINT": 1, "SMALLINT": 2, "INTEGER": 3, "INT": 3, "BIGINT": 4}
_SF_NUMBER_ALIASES = {"NUMBER", "NUMERIC", "DECIMAL"}


def _parse(t: str) -> tuple[str, list[int]]:
    t = t.upper().replace(" ", "")
    m = re.match(r"^([A-Z_]+)(?:\(([\d,]+)\))?", t)
    if not m:
        return t, []
    args = [int(x) for x in m.group(2).split(",")] if m.group(2) else []
    base = m.group(1)
    if base in _SF_NUMBER_ALIASES:
        base = "DECIMAL"
    if base in {"TIMESTAMP_NTZ", "TIMESTAMPNTZ", "DATETIME"}:
        base = "TIMESTAMP"
    if base in {"CHARACTER"}:
        base = "CHAR"
    if base in {"STRING", "TEXT"}:
        base = "VARCHAR"
    return base, args


def conform(legacy: str, target: str) -> tuple[bool, str]:
    lb, la = _parse(legacy)
    tb, ta = _parse(target)
    if lb in _INT_RANK and tb in _INT_RANK:
        ok = _INT_RANK[tb] >= _INT_RANK[lb]
        return ok, "integer widened" if ok and tb != lb else ("same" if ok else "integer narrowed")
    if lb in _INT_RANK and tb == "DECIMAL":
        p, s = (ta + [38, 0])[:2] if ta else (38, 0)
        return s == 0 and p >= 3 * _INT_RANK[lb], "integer as NUMBER"
    if lb == "DECIMAL" and tb == "DECIMAL":
        lp, ls = (la + [5, 0])[:2]
        tp, ts = (ta + [38, 0])[:2]
        if ts != ls:
            return False, f"scale changed {ls}\u2192{ts}"
        return tp >= lp, "same" if tp == lp else ("precision widened" if tp > lp else "precision narrowed")
    if lb in {"CHAR", "VARCHAR"} and tb in {"CHAR", "VARCHAR"}:
        ln = la[0] if la else 1
        tn = ta[0] if ta else 16_777_216
        return tn >= ln, "same" if (tn == ln and lb == tb) else ("length shortened" if tn < ln else "compatible")
    if lb in {"TIMESTAMP", "TIME"} and tb == lb:
        lp = la[0] if la else 6
        tp = ta[0] if ta else 9
        return tp >= lp, "same" if tp == lp else ("precision widened" if tp > lp else "fractional seconds lost")
    return lb == tb, "same" if lb == tb else f"{lb} \u2192 {tb}"


def compare_tables(legacy: TableDef, target: TableDef | None) -> list[dict[str, object]]:
    tcols = {c.name: c for c in target.columns} if target else {}
    rows = []
    for c in legacy.columns:
        t = tcols.get(c.name)
        if t is None:
            rows.append({"column": c.name, "legacy": c.declared_type, "target": "\u2014", "ok": False,
                         "note": "missing in target"})
            continue
        ok, note = conform(c.declared_type, t.declared_type)
        if c.nullable is False and t.nullable:
            ok, note = False, "NOT NULL dropped"
        rows.append({"column": c.name, "legacy": c.declared_type, "target": t.declared_type, "ok": ok, "note": note})
    return rows
