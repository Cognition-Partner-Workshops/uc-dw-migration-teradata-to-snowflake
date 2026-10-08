"""Azure Synapse dedicated SQL pool DDL (shared by the simulated and real connectors)."""

from __future__ import annotations

import re

from ...contracts.models import TablePlan
from .base import TargetBase, TargetConfigError, as_list, literal

_RANGE_N = re.compile(
    r"BETWEEN\s+DATE\s+'(\d{4})-(\d\d)-(\d\d)'\s+AND\s+DATE\s+'(\d{4})-\d\d-\d\d'", re.IGNORECASE
)


class SynapseDDL(TargetBase):
    def partition_boundaries(self, table: TablePlan) -> list[str]:
        explicit = as_list(self.opt(table, "partition_boundaries"))
        if explicit:
            return explicit
        m = _RANGE_N.search(table.source.partition_expression or "")
        if not m:
            raise TargetConfigError(
                f"{table.name}: Synapse partitioning needs boundary values: set 'partition_boundaries' "
                "(e.g. 2017-01-01,2018-01-01); none could be derived from a Teradata RANGE_N"
            )
        # Yearly boundaries: Synapse already splits every table into 60 distributions, so finer
        # (monthly) partitions would leave columnstore row groups far below 1M rows.
        return [f"{y}-01-01" for y in range(int(m.group(1)) + 1, int(m.group(4)) + 1)]

    def render_ddl(self, table: TablePlan, name: str | None = None) -> str:
        cols = self.columns(table)
        lines = [f"{self.q(c.name)} {c.type}{'' if c.nullable else ' NOT NULL'}" for c in cols]
        pk = self.primary_key(table)
        if pk and all(not c.nullable for c in pk):
            pk_cols = ", ".join(self.q(c.name) for c in pk)
            lines.append(
                f"CONSTRAINT {self.q('pk_' + (name or table.target_table))} "
                f"PRIMARY KEY NONCLUSTERED ({pk_cols}) NOT ENFORCED"
            )
        dist = str(self.opt(table, "distribution") or "ROUND_ROBIN").upper()
        if dist == "HASH":
            ref = self.opt(table, "distribution_column")
            if not ref:
                raise TargetConfigError(f"{table.name}: DISTRIBUTION = HASH requires 'distribution_column'")
            c = self.column(table, ref, "distribution_column")
            if "(MAX)" in c.type.upper().replace(" ", ""):
                raise TargetConfigError(f"{table.name}: hash column '{c.name}' cannot be a {c.type} column")
            with_parts = [f"DISTRIBUTION = HASH({self.q(c.name)})"]
        elif dist in ("ROUND_ROBIN", "REPLICATE"):
            with_parts = [f"DISTRIBUTION = {dist}"]
        else:
            raise TargetConfigError(
                f"{table.name}: unknown distribution '{dist}' (HASH, ROUND_ROBIN, REPLICATE)"
            )
        index = str(self.opt(table, "index_type") or "CLUSTERED_COLUMNSTORE").upper()
        if index == "CLUSTERED_COLUMNSTORE":
            with_parts.append("CLUSTERED COLUMNSTORE INDEX")
        elif index == "HEAP":
            with_parts.append("HEAP")
        elif index == "CLUSTERED_INDEX":
            if not pk:
                raise TargetConfigError(f"{table.name}: CLUSTERED_INDEX needs a primary/unique key to index")
            with_parts.append(f"CLUSTERED INDEX ({', '.join(self.q(c.name) for c in pk)})")
        else:
            raise TargetConfigError(f"{table.name}: unknown index_type '{index}'")
        part = self.opt(table, "partition_column")
        if part:
            pc = self.column(table, part, "partition_column")
            values = ", ".join(literal(v) for v in self.partition_boundaries(table))
            with_parts.append(f"PARTITION ({self.q(pc.name)} RANGE RIGHT FOR VALUES ({values}))")
        body = ",\n    ".join(lines)
        opts = ",\n    ".join(with_parts)
        return f"CREATE TABLE {self.qualified(table, name)}\n(\n    {body}\n)\nWITH\n(\n    {opts}\n);"

    def role_script_vars(self) -> dict[str, str]:
        return {"resource_class": str(self.opt(None, "resource_class") or "largerc")}
