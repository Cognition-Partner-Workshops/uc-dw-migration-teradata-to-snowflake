"""Shared helpers for target connectors: option resolution, column specs, checksum/profile SQL rendering,
role-script rendering, and the DuckDB-backed simulated warehouse used by all sim_* connectors."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ...contracts.checksum import duckdb_checksum_sql
from ...contracts.models import (
    ColumnProfile,
    ConnectionTestResult,
    LoadResult,
    MigrationPlan,
    ProfileSpec,
    TablePlan,
    TableProfile,
    TargetMeta,
    TargetTypeInfo,
)
from ...contracts.target import TargetConnector
from ...settings import get_settings
from ...typemap import arrow_type, is_fixed_width_char, target_type_info


class TargetConfigError(ValueError):
    """Invalid target options for a table (raised by render_ddl with an actionable message)."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str  # target column name
    source_name: str
    type: str  # effective native type
    info: TargetTypeInfo
    nullable: bool
    kind: str  # canonical checksum kind

    @property
    def arrow(self) -> pa.DataType:
        return arrow_type(self.info.arrow_type)


def canon_kind(meta: TargetMeta, type_str: str, t: pa.DataType) -> str:
    if pa.types.is_integer(t):
        return "integer"
    if pa.types.is_decimal(t):
        return "decimal"
    if pa.types.is_floating(t):
        return "float"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "timestamp_tz" if t.tz else "timestamp"
    if pa.types.is_time(t):
        return "time"
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_binary(t) or pa.types.is_large_binary(t):
        return "binary"
    return "char" if is_fixed_width_char(meta, type_str) else "string"


def column_specs(meta: TargetMeta, table: TablePlan) -> list[ColumnSpec]:
    out = []
    for c in table.columns:
        info = target_type_info(meta, c.effective_type)
        kind = canon_kind(meta, c.effective_type, arrow_type(info.arrow_type))
        out.append(ColumnSpec(c.target_name, c.source.name, c.effective_type, info, c.source.nullable, kind))
    return out


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


def literal(value: str) -> str:
    return value if re.fullmatch(r"-?\d+(\.\d+)?", value) else "'" + value.replace("'", "''") + "'"


def quote_ident(meta: TargetMeta, name: str) -> str:
    q = meta.identifiers.quote
    if q == "[":
        return "[" + name.replace("]", "]]") + "]"
    return q + name.replace(q, q + q) + q


# --------------------------------------------------------------------------------------------------
# Templates from targets_meta YAML
# --------------------------------------------------------------------------------------------------

_DIRECTIVE = re.compile(r"^\s*--\s*@([\w.]+):\s?(.*)$")


def parse_checksum_template(template: str) -> tuple[dict[str, str], str]:
    directives: dict[str, str] = {}
    body = []
    for line in template.splitlines():
        m = _DIRECTIVE.match(line)
        if m:
            directives[m.group(1)] = m.group(2).strip()
        else:
            body.append(line)
    return directives, "\n".join(body).strip()


def render_checksum_sql(meta: TargetMeta, relation: str, columns: list[ColumnSpec]) -> str:
    """Render meta.dq.checksum_sql_template (canonical checksum, see contracts/checksum.py)."""
    if not meta.dq.checksum_sql_template:
        raise ValueError(f"{meta.id}: dq.checksum_sql_template is not defined")
    d, body = parse_checksum_template(meta.dq.checksum_sql_template)
    parts = []
    for c in columns:
        expr = d.get(f"canon.{c.kind}", d["canon.string"])
        scale = str(c.arrow.scale) if pa.types.is_decimal(c.arrow) else "0"
        expr = expr.replace("{col}", quote_ident(meta, c.name)).replace("{scale}", scale)
        parts.append(f"COALESCE({expr}, {d['null']})")
    row = f" {d['concat']} {d['sep']} {d['concat']} ".join(parts)
    return body.replace("{row}", row).replace("{relation}", relation)


_VAR = re.compile(r"\{(\w+(?:\.\w+)?)\}")


def _fill(text: str, values: dict[str, str]) -> str:
    return _VAR.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def render_role_script(
    meta: TargetMeta, plan: MigrationPlan, qualify, extra: dict[str, str] | None = None
) -> str:
    """Render governance.role_script_template.

    Line prefixes: `@set k = v` defines a variable, `@table` repeats per table, `@piitable` per table with
    PII columns, `@pii` per PII column (masking != none). `{name}` placeholders are filled from context.
    """
    template = meta.governance.role_script_template or ""
    container = plan.tables[0].target_container if plan.tables else ""
    base = {"container": container, "target": meta.display_name, **(extra or {})}
    sets: dict[str, str] = {}
    out: list[str] = []

    def pii_cols(t: TablePlan):
        return [c for c in t.columns if c.pii and c.pii.masking != "none"]

    def col_vars(t: TablePlan, c) -> dict[str, str]:
        v = {**base, "table": t.target_table, "fq_table": qualify(t), "column": c.target_name}
        v |= {"q_column": quote_ident(meta, c.target_name), "column_type": c.effective_type}
        v |= {"category": c.pii.category, "masking": c.pii.masking}
        v["mask_expr"] = _fill(sets.get(f"mask.{c.pii.masking}", "NULL"), v)
        return v

    for line in template.splitlines():
        head, _, rest = line.partition(" ")
        if head == "@set":
            k, _, v = rest.partition("=")
            sets[k.strip()] = v.strip()
        elif head == "@table":
            out += [
                _fill(rest, {**base, "table": t.target_table, "fq_table": qualify(t)}) for t in plan.tables
            ]
        elif head == "@piitable":
            for t in plan.tables:
                cols = pii_cols(t)
                if cols:
                    repl = ", ".join(f"{(v := col_vars(t, c))['mask_expr']} AS {v['q_column']}" for c in cols)
                    v = {**base, "table": t.target_table, "fq_table": qualify(t), "masked_replace": repl}
                    out.append(_fill(rest, v))
        elif head == "@pii":
            out += [_fill(rest, col_vars(t, c)) for t in plan.tables for c in pii_cols(t)]
        else:
            out.append(_fill(line, base))
    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------------------------------------------
# Connector base
# --------------------------------------------------------------------------------------------------


class TargetBase(TargetConnector):
    """Option/column helpers shared by simulated and real connectors. Dialect mixins add render_ddl."""

    def opt(self, table: TablePlan | None, key: str) -> Any:
        if table is not None and table.target_options.get(key) not in (None, ""):
            return table.target_options[key]
        if self.config.get(key) not in (None, ""):
            return self.config[key]
        field = next((f for f in self.meta.config_fields if f.key == key), None)
        return field.default if field else None

    def q(self, name: str) -> str:
        return quote_ident(self.meta, name)

    def columns(self, table: TablePlan) -> list[ColumnSpec]:
        return column_specs(self.meta, table)

    def column(self, table: TablePlan, ref: str, option: str = "column") -> ColumnSpec:
        """Find a column by target or source name (case-insensitive)."""
        for c in self.columns(table):
            if ref.lower() in (c.name.lower(), c.source_name.lower()):
                return c
        raise TargetConfigError(f"{table.name}: {option} '{ref}' is not a column of the table")

    def primary_key(self, table: TablePlan) -> list[ColumnSpec]:
        src = table.source
        keys = (
            src.primary_index if src.primary_index_unique else (src.unique_keys[0] if src.unique_keys else [])
        )
        try:
            return [self.column(table, k) for k in keys]
        except TargetConfigError:
            return []

    def qualified(self, table: TablePlan, name: str | None = None) -> str:
        return f"{self.q(table.target_container)}.{self.q(name or table.target_table)}"

    def role_script_vars(self) -> dict[str, str]:
        return {}

    def access_script(self, plan: MigrationPlan) -> str:
        return render_role_script(self.meta, plan, self.qualified, self.role_script_vars())

    # ---- generic profiling SQL (all engines) ----
    def profile_sql(
        self, table: TablePlan, spec: ProfileSpec, relation: str, q=None
    ) -> tuple[str, list[tuple]]:
        q = q or self.q
        exprs, layout = ["COUNT(*)"], []
        for ref in dict.fromkeys(spec.null_columns + spec.numeric_columns):
            c = self.column(table, ref)
            qc = q(c.name)
            exprs.append(f"SUM(CASE WHEN {qc} IS NULL THEN 1 ELSE 0 END)")
            numeric = ref in spec.numeric_columns
            if numeric:
                summed = f"CAST({qc} AS BIGINT)" if c.kind == "integer" else qc
                exprs += [f"SUM({summed})", f"MIN({qc})", f"MAX({qc})"]
            layout.append((ref, numeric))
        return f"SELECT {', '.join(exprs)} FROM {relation}", layout

    def duplicate_key_sql(self, table: TablePlan, key: list[str], relation: str, q=None) -> str:
        q = q or self.q
        cols = ", ".join(q(self.column(table, k).name) for k in key)
        return (
            f"SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n FROM {relation} "
            f"GROUP BY {cols} HAVING COUNT(*) > 1) d"
        )

    def checksum_sql(self, table: TablePlan, spec: ProfileSpec, relation: str) -> str:
        cols = [self.column(table, ref) for ref in spec.checksum_columns]
        return render_checksum_sql(self.meta, relation, cols)

    def run_profile(self, table: TablePlan, spec: ProfileSpec, relation: str, query, q=None) -> TableProfile:
        """Profile via `query(sql) -> list[tuple]` using generic SQL + the dialect checksum."""
        sql, layout = self.profile_sql(table, spec, relation, q)
        row = list(query(sql)[0])
        prof = TableProfile(row_count=int(row.pop(0) or 0))
        for ref, numeric in layout:
            nulls = int(row.pop(0) or 0)
            cp = ColumnProfile(column=ref, null_count=nulls)
            if numeric:
                cp.sum, cp.min, cp.max = (
                    None if v is None else str(v) for v in (row.pop(0) for _ in range(3))
                )
            prof.columns.append(cp)
        for key in spec.unique_keys:
            prof.duplicate_key_count[",".join(key)] = int(
                query(self.duplicate_key_sql(table, key, relation, q))[0][0]
            )
        if spec.checksum_columns:
            prof.checksum = str(query(self.checksum_sql(table, spec, relation))[0][1])
        return prof


def missing_message(meta: TargetMeta, connection: dict[str, Any], keys: list[str]) -> str | None:
    missing = [k for k in keys if not connection.get(k)]
    if not missing:
        return None
    env = {f.key: f.env for f in meta.connection_fields}
    names = ", ".join(f"{k} (env {env[k]})" if env.get(k) else k for k in missing)
    return (
        f"{meta.display_name}: missing connection settings: {names}. Set them in .env or the connection form."
    )


def import_error_message(meta: TargetMeta, exc: ImportError) -> str:
    return (
        f"{meta.display_name} real mode needs the optional SDKs ({exc.name or exc}): "
        "pip install -e '.[real]' (the Docker image installs them)."
    )


# --------------------------------------------------------------------------------------------------
# Simulated warehouse (DuckDB file per target)
# --------------------------------------------------------------------------------------------------

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def duckdb_type(t: pa.DataType) -> str:
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_integer(t):
        return {8: "TINYINT", 16: "SMALLINT", 32: "INTEGER", 64: "BIGINT"}[t.bit_width]
    if pa.types.is_decimal(t):
        return f"DECIMAL({t.precision},{t.scale})" if t.precision <= 38 else "DOUBLE"
    if pa.types.is_floating(t):
        return "REAL" if t.bit_width == 32 else "DOUBLE"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_time(t):
        return "TIME"
    if pa.types.is_timestamp(t):
        return "TIMESTAMPTZ" if t.tz else "TIMESTAMP"
    if pa.types.is_binary(t) or pa.types.is_large_binary(t):
        return "BLOB"
    return "VARCHAR"


REGISTRY = "main._studio_tables"


def _duck_q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SimulatedTarget(TargetBase):
    """Stores data in `$DATA_DIR/targets/<target_id>.duckdb`; schema = TablePlan.target_container.

    One DuckDB connection per connector, one cursor per call; catalog changes (create/swap/drop) are
    serialized per database file so the pipeline can load several tables concurrently.
    """

    def __init__(self, meta: TargetMeta, connection: dict[str, Any], config: dict[str, Any]):
        super().__init__(meta, connection, config)
        path = connection.get("duckdb_path") or get_settings().sim_targets_dir / f"{meta.id}.duckdb"
        self.path = Path(path)
        self._con: duckdb.DuckDBPyConnection | None = None
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.path.resolve()), threading.RLock())

    # ---- plumbing ----
    def _cursor(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._con = duckdb.connect(str(self.path))
                self._con.execute(
                    f"CREATE TABLE IF NOT EXISTS {REGISTRY} (container VARCHAR, table_name VARCHAR, "
                    "native_ddl VARCHAR, duckdb_ddl VARCHAR, load_id VARCHAR, rows BIGINT, "
                    "updated_at TIMESTAMP, "
                    "PRIMARY KEY (container, table_name))"
                )
            return self._con.cursor()

    def _query(self, sql: str) -> list[tuple]:
        cur = self._cursor()
        try:
            return cur.execute(sql).fetchall()
        finally:
            cur.close()

    def duck_rel(self, table: TablePlan, name: str | None = None) -> str:
        return f'"{table.target_container}"."{name or table.target_table}"'

    def duckdb_ddl(self, table: TablePlan, name: str | None = None) -> str:
        cols = ",\n    ".join(
            f'"{c.name}" {duckdb_type(c.arrow)}{"" if c.nullable else " NOT NULL"}'
            for c in self.columns(table)
        )
        return f"CREATE TABLE {self.duck_rel(table, name)} (\n    {cols}\n)"

    def _register(self, cur, table: TablePlan, duck_ddl: str, load_id: str | None, rows: int | None) -> None:
        cur.execute(
            f"INSERT OR REPLACE INTO {REGISTRY} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                table.target_container,
                table.target_table,
                table.ddl or self.render_ddl(table),
                duck_ddl,
                load_id,
                rows,
                datetime.now(timezone.utc).replace(tzinfo=None),
            ],
        )

    def _table_exists(self, cur, table: TablePlan, name: str | None = None) -> bool:
        return bool(
            cur.execute(
                "SELECT 1 FROM duckdb_tables() WHERE database_name = current_database() "
                "AND schema_name = ? AND table_name = ?",
                [table.target_container, name or table.target_table],
            ).fetchall()
        )

    # ---- TargetConnector ----
    def test_connection(self) -> ConnectionTestResult:
        t0 = time.perf_counter()
        try:
            version = self._query("SELECT version()")[0][0]
        except Exception as exc:  # pragma: no cover - filesystem errors
            return ConnectionTestResult(ok=False, mode="simulated", message=f"cannot open {self.path}: {exc}")
        return ConnectionTestResult(
            ok=True,
            mode="simulated",
            latency_ms=(time.perf_counter() - t0) * 1000,
            server_version=f"simulated {self.meta.display_name} (DuckDB {version})",
            message=f"Simulated {self.meta.display_name} warehouse at {self.path}",
            details={"path": str(self.path)},
        )

    def ensure_container(self, container: str) -> None:
        with self._lock:
            cur = self._cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{container}"')
            cur.close()

    def create_table(self, table: TablePlan) -> None:
        self.render_ddl(table)  # validates target options
        ddl = self.duckdb_ddl(table)
        with self._lock:
            cur = self._cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{table.target_container}"')
            row = cur.execute(
                f"SELECT duckdb_ddl FROM {REGISTRY} WHERE container = ? AND table_name = ?",
                [table.target_container, table.target_table],
            ).fetchall()
            if not (row and row[0][0] == ddl and self._table_exists(cur, table)):
                cur.execute(ddl.replace("CREATE TABLE", "CREATE OR REPLACE TABLE", 1))
                self._register(cur, table, ddl, None, 0)
            cur.close()

    def _select_list(self, table: TablePlan, files: list[Path]) -> str:
        names = {n.lower(): n for n in pq.read_schema(files[0]).names}
        items = []
        for c in self.columns(table):
            src = names.get(c.name.lower()) or names.get(c.source_name.lower())
            if src is None:
                raise ValueError(f"{table.name}: column '{c.name}' not found in staged Parquet {files[0]}")
            items.append(f'CAST("{src}" AS {duckdb_type(c.arrow)}) AS "{c.name}"')
        return ", ".join(items)

    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        t0 = time.perf_counter()
        native = self.render_ddl(table)
        stg = f"{table.target_table}__stg_{re.sub(r'[^A-Za-z0-9_]', '_', load_id)}"
        ddl = self.duckdb_ddl(table)
        stg_ddl = self.duckdb_ddl(table, stg)
        with self._lock:
            cur = self._cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{table.target_container}"')
            for (old,) in cur.execute(
                "SELECT table_name FROM duckdb_tables() WHERE database_name = current_database() "
                "AND schema_name = ? AND starts_with(table_name, ?)",
                [table.target_container, f"{table.target_table}__stg_"],
            ).fetchall():
                cur.execute(f"DROP TABLE {self.duck_rel(table, old)}")
            cur.execute(stg_ddl)
        try:
            if files:
                paths = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
                cur.execute(
                    f"INSERT INTO {self.duck_rel(table, stg)} SELECT {self._select_list(table, files)} "
                    f"FROM read_parquet([{paths}])"
                )
            rows = cur.execute(f"SELECT COUNT(*) FROM {self.duck_rel(table, stg)}").fetchone()[0]
            with self._lock:
                cur.execute("BEGIN TRANSACTION")
                try:
                    cur.execute(f"DROP TABLE IF EXISTS {self.duck_rel(table)}")
                    cur.execute(f'ALTER TABLE {self.duck_rel(table, stg)} RENAME TO "{table.target_table}"')
                    self._register(cur, table, ddl, load_id, rows)
                    cur.execute("COMMIT")
                except Exception:
                    cur.execute("ROLLBACK")
                    raise
        except Exception:
            with self._lock:
                cur.execute(f"DROP TABLE IF EXISTS {self.duck_rel(table, stg)}")
            raise
        finally:
            cur.close()
        return LoadResult(
            rows_loaded=int(rows),
            load_id=load_id,
            duration_s=time.perf_counter() - t0,
            method=f"simulated:{table.load_method or self.opt(None, 'load_method')}",
            details={
                "engine": "duckdb",
                "path": str(self.path),
                "staging_table": stg,
                "swap": "DROP + RENAME in one transaction",
                "files": len(files),
                "native_ddl": native,
                "duckdb_ddl": ddl,
            },
        )

    def profile(self, table: TablePlan, spec: ProfileSpec) -> TableProfile:
        rel = self.duck_rel(table)
        checksum_spec = spec.model_copy(update={"checksum_columns": []})
        prof = self.run_profile(table, checksum_spec, rel, self._query, _duck_q)
        if spec.checksum_columns:
            cols = [self.column(table, ref) for ref in spec.checksum_columns]
            schema = pa.schema([(c.name, c.arrow) for c in cols])
            prof.checksum = str(self._query(duckdb_checksum_sql(rel, schema, [c.name for c in cols]))[0][1])
        return prof

    def drop_table(self, table: TablePlan) -> None:
        with self._lock:
            cur = self._cursor()
            cur.execute(f"DROP TABLE IF EXISTS {self.duck_rel(table)}")
            cur.execute(
                f"DELETE FROM {REGISTRY} WHERE container = ? AND table_name = ?",
                [table.target_container, table.target_table],
            )
            cur.close()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
