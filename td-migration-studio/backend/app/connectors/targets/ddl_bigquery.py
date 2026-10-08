"""Google BigQuery DDL (shared by the simulated and real connectors)."""

from __future__ import annotations

import pyarrow as pa

from ...contracts.models import TablePlan
from .base import ColumnSpec, TargetBase, TargetConfigError, as_list

MAX_CLUSTER_COLUMNS = 4


def _bq_kind(c: ColumnSpec) -> str:
    t = c.arrow
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_timestamp(t):
        return "TIMESTAMP" if t.tz else "DATETIME"
    if pa.types.is_integer(t):
        return "INT64"
    return c.type.upper()


class BigQueryDDL(TargetBase):
    @property
    def project(self) -> str | None:
        return self.connection.get("project") or None

    def qualified(self, table: TablePlan, name: str | None = None) -> str:
        parts = [self.project, table.target_container, name or table.target_table]
        return "`" + ".".join(p for p in parts if p) + "`"

    def partition_expr(self, table: TablePlan) -> str | None:
        ref = self.opt(table, "partition_column")
        if not ref:
            return None
        c = self.column(table, ref, "partition_column")
        gran = str(self.opt(table, "partition_granularity") or "MONTH").upper()
        if gran not in ("DAY", "MONTH", "YEAR"):
            raise TargetConfigError(f"{table.name}: partition_granularity must be DAY, MONTH or YEAR")
        kind, qc = _bq_kind(c), self.q(c.name)
        if kind == "DATE":
            return qc if gran == "DAY" else f"DATE_TRUNC({qc}, {gran})"
        if kind in ("DATETIME", "TIMESTAMP"):
            return f"DATE({qc})" if gran == "DAY" else f"{kind}_TRUNC({qc}, {gran})"
        if kind == "INT64":
            rng = as_list(self.opt(table, "partition_range"))
            if len(rng) != 3 or not all(v.lstrip("-").isdigit() for v in rng):
                raise TargetConfigError(
                    f"{table.name}: INT64 partition column '{c.name}' needs "
                    "partition_range 'start,end,interval'"
                )
            return f"RANGE_BUCKET({qc}, GENERATE_ARRAY({', '.join(rng)}))"
        raise TargetConfigError(
            f"{table.name}: partition column '{c.name}' is {c.type}; BigQuery partitions on "
            "DATE, DATETIME, TIMESTAMP or INT64 only"
        )

    def clustering(self, table: TablePlan) -> list[ColumnSpec]:
        refs = as_list(self.opt(table, "clustering_columns"))
        if len(refs) > MAX_CLUSTER_COLUMNS:
            raise TargetConfigError(
                f"{table.name}: BigQuery allows at most 4 clustering columns ({len(refs)} given)"
            )
        cols = [self.column(table, r, "clustering column") for r in refs]
        for c in cols:
            if c.kind in ("float", "binary", "time") or c.type.upper().startswith(("JSON", "GEOGRAPHY")):
                raise TargetConfigError(f"{table.name}: cannot cluster by {c.type} column '{c.name}'")
        return cols

    def render_ddl(self, table: TablePlan, name: str | None = None) -> str:
        lines = [f"{self.q(c.name)} {c.type}{'' if c.nullable else ' NOT NULL'}" for c in self.columns(table)]
        pk = self.primary_key(table)
        if pk:
            lines.append(f"PRIMARY KEY ({', '.join(self.q(c.name) for c in pk)}) NOT ENFORCED")
        out = [f"CREATE TABLE {self.qualified(table, name)}\n(\n  " + ",\n  ".join(lines) + "\n)"]
        part = self.partition_expr(table)
        if part:
            out.append(f"PARTITION BY {part}")
        cluster = self.clustering(table)
        if cluster:
            out.append("CLUSTER BY " + ", ".join(self.q(c.name) for c in cluster))
        if self.opt(table, "require_partition_filter") in (True, "true", "TRUE", 1):
            if not part:
                raise TargetConfigError(f"{table.name}: require_partition_filter needs a partition_column")
            out.append("OPTIONS (require_partition_filter = TRUE)")
        return "\n".join(out) + ";"

    def role_script_vars(self) -> dict[str, str]:
        return {"project": self.project or "my-project", "location": str(self.opt(None, "location") or "US")}
