"""Reconcile legacy vs target result sets and produce regulator-facing checks."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from .engines import QueryResult

PASS, WAIVED, FAIL, ERROR = "PASS", "PASS_WITH_WAIVERS", "FAIL", "ERROR"
NUMERIC_TOLERANCE = Decimal("0.000001")
SAMPLE_LIMIT = 15


@dataclass
class Waiver:
    object: str
    column: str
    reason: str
    approver_role: str


@dataclass
class ColumnCheck:
    column: str
    legacy_type: str
    target_type: str
    type_drift: bool
    legacy_nulls: int
    target_nulls: int
    legacy_distinct: int
    target_distinct: int
    legacy_sum: str | None
    target_sum: str | None
    mismatched_rows: int
    waived: Waiver | None = None

    @property
    def ok(self) -> bool:
        if self.waived:
            return True
        return (not self.type_drift and self.mismatched_rows == 0 and self.legacy_nulls == self.target_nulls
                and self.legacy_distinct == self.target_distinct and self.legacy_sum == self.target_sum)


@dataclass
class ObjectReport:
    kind: str
    name: str
    status: str
    key: list[str] = field(default_factory=list)
    legacy_rows: int = 0
    target_rows: int = 0
    legacy_fingerprint: str = ""
    target_fingerprint: str = ""
    missing_in_target: int = 0
    extra_in_target: int = 0
    changed_rows: int = 0
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    columns: list[ColumnCheck] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    control_totals: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    error: str | None = None
    nondeterministic: bool = False
    findings: list[str] = field(default_factory=list)


_NUMERIC = re.compile(r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|DECIMAL|DOUBLE|FLOAT|REAL|UBIGINT|UINTEGER)", re.I)


def type_family(t: str) -> str:
    t = t.upper()
    if _NUMERIC.match(t):
        return "NUMBER"
    if t.startswith(("VARCHAR", "CHAR", "TEXT", "STRING")):
        return "TEXT"
    if t.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    return t.split("(")[0]


def canonical(value: Any) -> str:
    """Engine-independent text form used for hashing and comparison."""
    if value is None:
        return "\u2205"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, Decimal, float)):
        try:
            d = Decimal(str(value)).quantize(NUMERIC_TOLERANCE)
        except InvalidOperation:
            return str(value)
        return format(d.normalize(), "f") if d != 0 else "0"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _row_hash(values: list[str]) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def fingerprint(rows: list[list[str]]) -> str:
    """Order-independent SHA-256 over all canonical rows."""
    h = hashlib.sha256()
    for rh in sorted(_row_hash(r) for r in rows):
        h.update(rh.encode())
    return h.hexdigest()


def _sum(values: list[str], family: str) -> str | None:
    if family != "NUMBER":
        return None
    total = Decimal(0)
    for v in values:
        if v != "\u2205":
            try:
                total += Decimal(v)
            except InvalidOperation:
                return "n/a"
    return canonical(total)


def reconcile(
    kind: str,
    name: str,
    legacy: QueryResult,
    target: QueryResult,
    key: list[str] | None = None,
    waivers: list[Waiver] | None = None,
    controls: list[dict[str, Any]] | None = None,
) -> ObjectReport:
    rep = ObjectReport(kind=kind, name=name, status=PASS, key=list(key or []))
    lcols = [c.upper() for c in legacy.columns]
    tcols = [c.upper() for c in target.columns]
    rep.missing_columns = [c for c in lcols if c not in tcols]
    rep.extra_columns = [c for c in tcols if c not in lcols]
    common = [c for c in lcols if c in tcols]
    waived = {w.column.upper(): w for w in (waivers or []) if w.object.upper() == name.upper()}
    compared = [c for c in common if c not in waived]

    li = [lcols.index(c) for c in common]
    ti = [tcols.index(c) for c in common]
    lrows = [[canonical(r[i]) for i in li] for r in legacy.rows]
    trows = [[canonical(r[i]) for i in ti] for r in target.rows]
    cmp_idx = [common.index(c) for c in compared]
    rep.legacy_rows, rep.target_rows = len(lrows), len(trows)
    rep.legacy_fingerprint = fingerprint([[r[i] for i in cmp_idx] for r in lrows])
    rep.target_fingerprint = fingerprint([[r[i] for i in cmp_idx] for r in trows])

    key_cols = [k.upper() for k in rep.key if k.upper() in common]
    col_mismatch: Counter[str] = Counter()
    if key_cols:
        kidx = [common.index(k) for k in key_cols]
        lmap = {tuple(r[i] for i in kidx): r for r in lrows}
        tmap = {tuple(r[i] for i in kidx): r for r in trows}
        missing = [k for k in lmap if k not in tmap]
        extra = [k for k in tmap if k not in lmap]
        rep.missing_in_target, rep.extra_in_target = len(missing), len(extra)
        for k in sorted(missing)[:5]:
            rep.samples.append({"type": "missing in target", "key": dict(zip(key_cols, k))})
        for k in sorted(extra)[:5]:
            rep.samples.append({"type": "extra in target", "key": dict(zip(key_cols, k))})
        for k in sorted(set(lmap) & set(tmap)):
            lr, tr = lmap[k], tmap[k]
            diffs = {c: (lr[i], tr[i]) for c, i in zip(compared, cmp_idx) if lr[i] != tr[i]}
            if diffs:
                rep.changed_rows += 1
                col_mismatch.update(diffs.keys())
                if len(rep.samples) < SAMPLE_LIMIT:
                    rep.samples.append({"type": "value differs", "key": dict(zip(key_cols, k)),
                                        "diffs": {c: {"legacy": a, "target": b} for c, a, b in
                                                  ((c, *v) for c, v in list(diffs.items())[:4])}})
    else:
        lc = Counter(tuple(r[i] for i in cmp_idx) for r in lrows)
        tc = Counter(tuple(r[i] for i in cmp_idx) for r in trows)
        rep.missing_in_target = sum((lc - tc).values())
        rep.extra_in_target = sum((tc - lc).values())
        for row in list((lc - tc).elements())[:3]:
            rep.samples.append({"type": "missing in target", "row": dict(zip(compared, row))})
        for row in list((tc - lc).elements())[:3]:
            rep.samples.append({"type": "extra in target", "row": dict(zip(compared, row))})

    for c in common:
        i = common.index(c)
        lt, tt = legacy.types[lcols.index(c)], target.types[tcols.index(c)]
        lvals, tvals = [r[i] for r in lrows], [r[i] for r in trows]
        rep.columns.append(ColumnCheck(
            column=c, legacy_type=lt, target_type=tt, type_drift=type_family(lt) != type_family(tt),
            legacy_nulls=lvals.count("\u2205"), target_nulls=tvals.count("\u2205"),
            legacy_distinct=len(set(lvals)), target_distinct=len(set(tvals)),
            legacy_sum=_sum(lvals, type_family(lt)),
            target_sum=_sum(tvals, type_family(tt)) if type_family(tt) == "NUMBER" else None,
            mismatched_rows=col_mismatch.get(c, 0), waived=waived.get(c),
        ))

    for ctl in controls or []:
        rep.control_totals.append(_control_total(ctl, common, lrows, trows))

    _summarise(rep, waived)
    return rep


def _control_total(ctl: dict[str, Any], common: list[str], lrows: list[list[str]],
                   trows: list[list[str]]) -> dict[str, Any]:
    group, measure = ctl["group_by"].upper(), ctl["measure"].upper()
    out: dict[str, Any] = {"label": ctl.get("label", f"SUM({measure}) BY {group}"), "rows": [], "ok": True}
    if group not in common or measure not in common:
        out["ok"] = False
        out["error"] = "control columns not present in both results"
        return out
    gi, mi = common.index(group), common.index(measure)

    def agg(rows: list[list[str]]) -> dict[str, tuple[int, Decimal]]:
        acc: dict[str, list[Any]] = {}
        for r in rows:
            slot = acc.setdefault(r[gi], [0, Decimal(0)])
            slot[0] += 1
            try:
                slot[1] += Decimal(r[mi]) if r[mi] != "\u2205" else 0
            except InvalidOperation:
                pass
        return {k: (v[0], v[1]) for k, v in acc.items()}

    la, ta = agg(lrows), agg(trows)
    for g in sorted(set(la) | set(ta)):
        lcount, lsum = la.get(g, (0, Decimal(0)))
        tcount, tsum = ta.get(g, (0, Decimal(0)))
        ok = lcount == tcount and canonical(lsum) == canonical(tsum)
        out["ok"] &= ok
        out["rows"].append({"group": g, "legacy_count": lcount, "target_count": tcount,
                            "legacy_sum": canonical(lsum), "target_sum": canonical(tsum), "ok": ok})
    return out


def _summarise(rep: ObjectReport, waived: dict[str, Waiver]) -> None:
    f = rep.findings
    if rep.missing_columns:
        f.append(f"Columns missing in target: {', '.join(rep.missing_columns)}")
    if rep.legacy_rows != rep.target_rows:
        f.append(f"Row count differs: legacy {rep.legacy_rows:,} vs target {rep.target_rows:,}")
    if rep.missing_in_target or rep.extra_in_target:
        f.append(f"{rep.missing_in_target:,} rows missing in target, {rep.extra_in_target:,} unexpected rows")
    if rep.changed_rows:
        f.append(f"{rep.changed_rows:,} rows have different values")
    for c in rep.columns:
        if c.waived:
            continue
        if c.type_drift:
            f.append(f"{c.column}: type drift {c.legacy_type} \u2192 {c.target_type}")
        elif c.mismatched_rows:
            f.append(f"{c.column}: {c.mismatched_rows:,} rows differ")
        elif c.legacy_sum != c.target_sum and c.legacy_sum is not None:
            f.append(f"{c.column}: control total differs ({c.legacy_sum} vs {c.target_sum})")
    for ct in rep.control_totals:
        if not ct["ok"]:
            f.append(f"Control total failed: {ct['label']}")
    clean = (not rep.missing_columns and rep.legacy_fingerprint == rep.target_fingerprint
             and rep.legacy_rows == rep.target_rows and all(c.ok for c in rep.columns)
             and all(ct["ok"] for ct in rep.control_totals))
    if not clean:
        rep.status = FAIL
    elif waived:
        rep.status = WAIVED
