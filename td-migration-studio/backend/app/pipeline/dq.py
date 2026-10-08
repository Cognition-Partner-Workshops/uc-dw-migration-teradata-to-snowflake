"""Data-quality + reconciliation: DuckDB profiles over staged Parquet, RI orphan counts, check evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb
import pyarrow as pa

from ..contracts.checksum import duckdb_checksum_sql
from ..contracts.models import (
    CheckResult,
    ColumnProfile,
    DQOptions,
    ForeignKey,
    ProfileSpec,
    TableProfile,
)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _relation(con: duckdb.DuckDBPyConnection, files: list[Path], schema: pa.Schema, alias: str) -> str:
    if files:
        paths = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
        con.execute(f"CREATE OR REPLACE VIEW {alias} AS SELECT * FROM read_parquet([{paths}])")
    else:
        con.register(alias, schema.empty_table())
    return alias


def profile_parquet(files: list[Path], schema: pa.Schema, spec: ProfileSpec) -> TableProfile:
    """The staged-side reference profile (same definitions the targets implement)."""
    con = duckdb.connect()
    try:
        rel = _relation(con, files, schema, "staged")
        exprs = ["COUNT(*)"]
        for c in spec.null_columns:
            exprs.append(f"COUNT(*) - COUNT({_q(c)})")
        for c in spec.numeric_columns:
            exprs += [f"CAST({fn}({_q(c)}) AS VARCHAR)" for fn in ("SUM", "MIN", "MAX")]
        row = con.execute(f"SELECT {', '.join(exprs)} FROM {rel}").fetchone()
        assert row is not None
        rows, vals = row[0], list(row[1:])
        nulls = dict(zip(spec.null_columns, vals[: len(spec.null_columns)], strict=True))
        aggs = vals[len(spec.null_columns) :]
        cols: dict[str, ColumnProfile] = {c: ColumnProfile(column=c, null_count=n) for c, n in nulls.items()}
        for i, c in enumerate(spec.numeric_columns):
            cp = cols.setdefault(c, ColumnProfile(column=c, null_count=0))
            cp.sum, cp.min, cp.max = aggs[3 * i : 3 * i + 3]
        checksum = None
        if spec.checksum_columns:
            checksum = con.execute(duckdb_checksum_sql(rel, schema, spec.checksum_columns)).fetchone()[1]  # type: ignore[index]
        dups = {}
        for key in spec.unique_keys:
            k = ", ".join(_q(c) for c in key)
            dups[",".join(key)] = con.execute(
                f"SELECT COALESCE(SUM(n - 1), 0) FROM "
                f"(SELECT COUNT(*) n FROM {rel} GROUP BY {k} HAVING COUNT(*) > 1)"
            ).fetchone()[0]  # type: ignore[index]
        return TableProfile(
            row_count=rows,
            columns=list(cols.values()),
            checksum=checksum,
            duplicate_key_count={k: int(v) for k, v in dups.items()},
        )
    finally:
        con.close()


@dataclass
class OrphanResult:
    fk: ForeignKey
    child_columns: list[str]
    parent_table: str
    child_rows: int
    orphans: int
    sample: list[str] = field(default_factory=list)


def orphan_count(
    child_files: list[Path],
    child_schema: pa.Schema,
    child_cols: list[str],
    parent_files: list[Path],
    parent_schema: pa.Schema,
    parent_cols: list[str],
    sample: int = 5,
) -> tuple[int, int, list[str]]:
    """(non-null child FK rows, orphan rows, sample orphan keys) using staged Parquet on both sides."""
    con = duckdb.connect()
    try:
        c = _relation(con, child_files, child_schema, "child")
        p = _relation(con, parent_files, parent_schema, "parent")
        notnull = " AND ".join(f"c.{_q(x)} IS NOT NULL" for x in child_cols)
        join = " AND ".join(
            f"p.{_q(pc)} = c.{_q(cc)}" for cc, pc in zip(child_cols, parent_cols, strict=True)
        )
        base = f"FROM {c} c WHERE {notnull}"
        orphan = f"{base} AND NOT EXISTS (SELECT 1 FROM {p} p WHERE {join})"
        total = con.execute(f"SELECT COUNT(*) {base}").fetchone()[0]  # type: ignore[index]
        n = con.execute(f"SELECT COUNT(*) {orphan}").fetchone()[0]  # type: ignore[index]
        key = " || ',' || ".join(f"CAST(c.{_q(x)} AS VARCHAR)" for x in child_cols)
        rows = (
            con.execute(f"SELECT DISTINCT {key} {orphan} ORDER BY 1 LIMIT {sample}").fetchall() if n else []
        )
        return int(total), int(n), [r[0] for r in rows]
    finally:
        con.close()


# --------------------------------------------------------------------------------------------------
# Check evaluation
# --------------------------------------------------------------------------------------------------


def _dec(v: str | None) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _within(a: str | None, b: str | None, tol_pct: float) -> tuple[bool, str | None]:
    """Relative difference in percent between a (reference) and b; both None counts as equal."""
    da, db = _dec(a), _dec(b)
    if da is None and db is None:
        return a == b, None
    if da is None or db is None:
        return False, None
    diff = db - da
    if diff == 0:
        return True, "0"
    rel = abs(diff) / max(abs(da), Decimal("1e-12")) * 100
    return rel <= Decimal(str(tol_pct)), f"{diff.normalize():f} ({rel:.6f}%)"


def _pct(n: int, d: int) -> float:
    return (n / d * 100) if d else 0.0


@dataclass
class ColumnDQ:
    source: str
    target: str
    numeric: bool
    touched: bool


def evaluate(
    columns: list[ColumnDQ],
    unique_keys: list[list[str]],
    source: TableProfile,
    staged: TableProfile,
    target: TableProfile,
    rejected_rows: int,
    orphans: list[OrphanResult],
    opts: DQOptions,
) -> list[CheckResult]:
    th = opts.thresholds
    checks: list[CheckResult] = []
    src_cols = {c.column: c for c in source.columns}
    stg_cols = {c.column: c for c in staged.columns}
    tgt_cols = {c.column: c for c in target.columns}
    source_comparable = rejected_rows == 0

    if opts.row_count:
        expected = source.row_count - rejected_rows
        diff = target.row_count - expected
        checks.append(
            CheckResult(
                name="row_count",
                source_value=str(expected),
                target_value=str(target.row_count),
                diff=str(diff),
                threshold=f"{th.row_count_tolerance_pct}%",
                passed=_pct(abs(diff), max(expected, 1)) <= th.row_count_tolerance_pct
                and staged.row_count == expected,
                detail=f"source {source.row_count:,} - rejected {rejected_rows:,} = {expected:,}; "
                f"staged {staged.row_count:,}",
            )
        )

    if opts.aggregates:
        for c in (c for c in columns if c.numeric):
            s, t, src = stg_cols.get(c.target), tgt_cols.get(c.target), src_cols.get(c.source)
            if s is None or t is None:
                continue
            for agg in ("sum", "min", "max"):
                sv, tv = getattr(s, agg), getattr(t, agg)
                ok, diff = _within(sv, tv, th.aggregate_tolerance_pct)
                ref, detail = sv, f"staged={sv} target={tv}"
                if src is not None and not c.touched and source_comparable:
                    srcv = getattr(src, agg)
                    ok_src, _ = _within(srcv, sv, th.aggregate_tolerance_pct)
                    ok = ok and ok_src
                    ref, detail = srcv, f"source={srcv} staged={sv} target={tv}"
                elif c.touched:
                    detail += " (column transformed; compared staged vs target)"
                checks.append(
                    CheckResult(
                        name=agg,
                        column=c.target,
                        source_value=ref,
                        target_value=tv,
                        diff=diff,
                        threshold=f"{th.aggregate_tolerance_pct}%",
                        passed=ok,
                        detail=detail,
                    )
                )

    if opts.null_ratio:
        for c in columns:
            s, t, src = stg_cols.get(c.target), tgt_cols.get(c.target), src_cols.get(c.source)
            if s is None or t is None:
                continue
            sr, tr = _pct(s.null_count, staged.row_count), _pct(t.null_count, target.row_count)
            ok = abs(sr - tr) <= th.null_ratio_tolerance_pct
            ref, detail = sr, f"staged nulls={s.null_count:,} target nulls={t.null_count:,}"
            if src is not None and not c.touched and source_comparable:
                r = _pct(src.null_count, source.row_count)
                ok = ok and abs(r - sr) <= th.null_ratio_tolerance_pct
                ref, detail = r, f"source nulls={src.null_count:,} " + detail
            checks.append(
                CheckResult(
                    name="null_ratio",
                    column=c.target,
                    source_value=f"{ref:.4f}%",
                    target_value=f"{tr:.4f}%",
                    diff=f"{tr - ref:.4f}",
                    threshold=f"{th.null_ratio_tolerance_pct}%",
                    passed=ok,
                    detail=detail,
                )
            )

    if opts.checksum and staged.checksum is not None:
        ok = target.checksum is not None and staged.checksum == target.checksum
        checks.append(
            CheckResult(
                name="checksum",
                source_value=staged.checksum,
                target_value=target.checksum,
                passed=ok,
                detail="canonical row checksum: staged Parquet (DuckDB) vs target engine"
                if target.checksum is not None
                else "target did not return a checksum",
            )
        )

    if opts.uniqueness:
        for key in unique_keys:
            k = ",".join(key)
            sd, td = staged.duplicate_key_count.get(k, 0), target.duplicate_key_count.get(k)
            ok = sd == 0 and (td or 0) == 0
            checks.append(
                CheckResult(
                    name="uniqueness",
                    column=k,
                    source_value=str(sd),
                    target_value=str(td),
                    threshold="0 duplicates",
                    passed=ok,
                    detail="duplicate rows beyond the first per key (staged / target)",
                )
            )

    if opts.referential_integrity:
        for o in orphans:
            pct = _pct(o.orphans, o.child_rows)
            limit = 0.0 if o.fk.enforced else th.max_orphan_rows_pct
            ok = pct <= limit
            kind = "enforced FK" if o.fk.enforced else "soft RI (informational within threshold)"
            detail = f"{o.orphans:,} of {o.child_rows:,} rows have no parent in {o.parent_table} "
            detail += f"({pct:.3f}%, {kind})"
            if o.sample:
                detail += f"; e.g. {', '.join(o.sample)}"
            checks.append(
                CheckResult(
                    name="referential_integrity",
                    column=",".join(o.child_columns),
                    source_value=str(o.child_rows),
                    target_value=str(o.orphans),
                    diff=f"{pct:.4f}%",
                    threshold=f"{limit}%",
                    passed=ok,
                    detail=detail,
                )
            )

    pct = _pct(rejected_rows, source.row_count)
    checks.append(
        CheckResult(
            name="rejected_rows",
            source_value=str(source.row_count),
            target_value=str(rejected_rows),
            diff=f"{pct:.4f}%",
            threshold=f"{th.max_rejected_rows_pct}%",
            passed=pct <= th.max_rejected_rows_pct,
            detail=f"{rejected_rows:,} rows written to rejects",
        )
    )
    return checks
