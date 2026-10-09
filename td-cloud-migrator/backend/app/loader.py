"""Simulated cloud load: create the converted structures in a local DuckDB per target, load validated rows, reconcile."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import sqlglot

from .conversion import numeric_columns
from .data_analyser import TablePlan
from .ddl_render import target_schema
from .models import (
    Conversion,
    LoadResult,
    SourceObject,
    TableLoadResult,
    TableMeta,
    TargetId,
    ViewLoadResult,
)
from .sql_convert import _draft, preprocess, split_view, view_ddl
from .typemap import duckdb_type, map_type

DIALECT = {"bigquery": "bigquery", "redshift": "redshift", "synapse": "tsql"}
NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "DECIMAL", "DOUBLE", "FLOAT", "HUGEINT")


def simulated_type(col, target: TargetId) -> str:
    """The *target* type (e.g. INT64, NVARCHAR(40)) expressed in DuckDB, so each simulator mirrors its target."""
    target_type = map_type(col, target).type
    try:
        cast = sqlglot.parse_one(f"CAST(x AS {target_type})", read=DIALECT[target]).sql("duckdb")
        return re.search(r"AS (.+)\)$", cast).group(1)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return duckdb_type(col)


def _default_sql(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?|'(?:[^']|'')*'", v):
        return v
    if re.fullmatch(r"(DATE|TIMESTAMP)\s*'[^']*'", v, re.IGNORECASE):
        return v
    if v.upper() in ("CURRENT_DATE", "DATE"):
        return "CURRENT_DATE"
    if v.upper().startswith("CURRENT_TIMESTAMP"):
        return "CURRENT_TIMESTAMP"
    return None


def create_table_sql(t: TableMeta, schema: str, target: TargetId) -> list[str]:
    stmts, cols = [], []
    for c in t.columns:
        s = f'"{c.name}" {simulated_type(c, target)}'
        if c.identity:
            seq = f'"{schema}"."seq_{t.name}_{c.name}"'
            stmts.append(f"CREATE SEQUENCE IF NOT EXISTS {seq} START {c.identity.start} INCREMENT {c.identity.increment}")
            s += f" DEFAULT nextval('{schema}.seq_{t.name}_{c.name}')"
        elif (d := _default_sql(c.default)) is not None:
            s += f" DEFAULT {d}"
        if not c.nullable:
            s += " NOT NULL"
        cols.append(s)
    stmts.append(f'CREATE OR REPLACE TABLE "{schema}"."{t.name}" (\n  ' + ",\n  ".join(cols) + "\n)")
    return stmts


def _arrow_value(v):
    return float(v) if isinstance(v, Decimal) else v


def _reconcile(con, fq: str, t: TableMeta, plan: TablePlan) -> tuple[int, int, list[str]]:
    """Row count + per-column NULL count + numeric SUM / string length checksum: source rows vs loaded table."""
    failed: list[str] = []
    total = 1
    loaded = con.execute(f"SELECT COUNT(*) FROM {fq}").fetchone()[0]
    if loaded != len(plan.rows):
        failed.append(f"row count: expected {len(plan.rows)}, loaded {loaded}")
    for i, name in enumerate(plan.load_columns):
        col = t.column(name)
        vals = [r[i] for r in plan.rows]
        exp_nulls = sum(v is None for v in vals)
        got_nulls = con.execute(f'SELECT COUNT(*) FILTER (WHERE "{name}" IS NULL) FROM {fq}').fetchone()[0]
        total += 1
        if got_nulls != exp_nulls:
            failed.append(f"{name} NULL count: expected {exp_nulls}, got {got_nulls}")
        nn = [v for v in vals if v is not None]
        if col and col.base_type.value in ("BYTEINT", "SMALLINT", "INTEGER", "BIGINT", "DECIMAL", "NUMBER"):
            total += 1
            expected = sum((Decimal(str(v)) for v in nn), Decimal(0))
            got = con.execute(f'SELECT SUM("{name}") FROM {fq}').fetchone()[0] or 0
            if abs(Decimal(str(got)) - expected) > Decimal("0.0001"):
                failed.append(f"{name} SUM: expected {expected}, got {got}")
        elif col and col.base_type.value in ("CHAR", "VARCHAR"):
            total += 1
            expected = sum(len(str(v).rstrip()) for v in nn)
            got = con.execute(f'SELECT SUM(LENGTH(RTRIM("{name}"))) FROM {fq}').fetchone()[0] or 0
            if got != expected:
                failed.append(f"{name} length checksum: expected {expected}, got {got}")
    return total - len(failed), total, failed


def run_load(
    target: TargetId,
    db_path: Path,
    objects: list[SourceObject],
    order: list[str],
    plans: dict[str, TablePlan],
    conversions: list[Conversion],
    schema_map: dict[str, str],
) -> LoadResult:
    started = datetime.now(timezone.utc).isoformat()
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    by_id = {o.id: o for o in objects}
    conv = {c.object_id: c for c in conversions if c.target == target}
    tables: list[TableLoadResult] = []
    views: list[ViewLoadResult] = []
    for oid in order:
        o = by_id[oid]
        if o.object_type != "table" or not o.table:
            continue
        t = o.table
        schema = target_schema(t.database, schema_map)
        fq = f'"{schema}"."{t.name}"'
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        plan = plans.get(oid)
        res = TableLoadResult(table_id=oid, target_table=f"{schema}.{t.name}", created=False, status="failed")
        try:
            for s in create_table_sql(t, schema, target):
                con.execute(s)
            res.created = True
        except Exception as exc:  # noqa: BLE001
            res.error = f"CREATE failed: {exc}"
            tables.append(res)
            continue
        if not plan or plan.readiness.status == "no_data":
            res.status = "structure_only"
            tables.append(res)
            continue
        r = plan.readiness
        res.files, res.source_rows, res.rejected_rows = r.files, r.total_rows, r.rejected_rows + r.duplicate_rows
        if r.status == "blocked":
            res.error = "; ".join(r.issues) or "blocked by data validation"
            tables.append(res)
            continue
        try:
            arrow = (
                pa.table({n: [_arrow_value(row[i]) for row in plan.rows] for i, n in enumerate(plan.load_columns)}) if plan.rows else None
            )
            if arrow is not None:
                con.register("staging", arrow)
                cols = ", ".join(f'"{n}"' for n in plan.load_columns)
                types = {c.name: simulated_type(c, target) for c in t.columns}
                sel = ", ".join(f'CAST("{n}" AS {types[n]})' for n in plan.load_columns)
                con.execute(f"INSERT INTO {fq} ({cols}) SELECT {sel} FROM staging")
                con.unregister("staging")
            res.loaded_rows = con.execute(f"SELECT COUNT(*) FROM {fq}").fetchone()[0]
            res.checks_passed, res.checks_total, res.failed_checks = _reconcile(con, fq, t, plan)
            if res.failed_checks:
                res.status = "failed"
            else:
                res.status = "passed_with_rejects" if res.rejected_rows else "passed"
        except Exception as exc:  # noqa: BLE001
            res.error = f"Load failed: {exc}"
        tables.append(res)
    for oid in order:
        o = by_id[oid]
        if o.object_type != "view":
            continue
        c = conv.get(oid)
        schema = target_schema(o.database, schema_map)
        vr = ViewLoadResult(object_id=oid, target_view=f"{schema}.{o.name}", created=False)
        if c is None or c.status == "unsupported":
            vr.error = "Not converted"
            views.append(vr)
            continue
        try:
            _, _, body = split_view(o.sql)
            pre, _, _ = preprocess(body)
            sql, _ = _draft(pre, "duckdb", schema_map, "", numeric_columns(objects))
            con.execute(view_ddl(o, "duckdb", sql, schema_map, ""))
            vr.created = True
            vr.row_count = con.execute(f'SELECT COUNT(*) FROM "{schema}"."{o.name}"').fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            vr.error = str(exc).splitlines()[0][:300]
        views.append(vr)
    con.close()
    bad = [t for t in tables if t.status == "failed"]
    warn = [t for t in tables if t.status in ("passed_with_rejects", "structure_only")] or [v for v in views if not v.created]
    return LoadResult(
        target=target,
        database_file=db_path.name,
        tables=tables,
        views=views,
        status="failed" if bad else ("passed_with_warnings" if warn else "passed"),
        started_at=started,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
