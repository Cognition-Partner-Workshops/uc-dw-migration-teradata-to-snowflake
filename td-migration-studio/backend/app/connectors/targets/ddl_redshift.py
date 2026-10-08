"""Amazon Redshift DDL (shared by the simulated and real connectors)."""

from __future__ import annotations

from ...contracts.models import TablePlan
from .base import TargetBase, TargetConfigError, as_list


class RedshiftDDL(TargetBase):
    def render_ddl(self, table: TablePlan, name: str | None = None) -> str:
        lines = [f"{self.q(c.name)} {c.type}{'' if c.nullable else ' NOT NULL'}" for c in self.columns(table)]
        pk = self.primary_key(table)
        if pk:
            lines.append(f"PRIMARY KEY ({', '.join(self.q(c.name) for c in pk)})")
        out = [f"CREATE TABLE {self.qualified(table, name)}\n(\n    " + ",\n    ".join(lines) + "\n)"]
        style = str(self.opt(table, "diststyle") or "AUTO").upper()
        distkey = self.opt(table, "distkey")
        if style not in ("AUTO", "KEY", "EVEN", "ALL"):
            raise TargetConfigError(f"{table.name}: unknown diststyle '{style}' (AUTO, KEY, EVEN, ALL)")
        if style == "KEY":
            if not distkey:
                raise TargetConfigError(f"{table.name}: DISTSTYLE KEY requires 'distkey'")
            out.append(f"DISTSTYLE KEY\nDISTKEY ({self.q(self.column(table, distkey, 'distkey').name)})")
        else:
            if distkey:
                raise TargetConfigError(
                    f"{table.name}: distkey is only valid with DISTSTYLE KEY (got {style})"
                )
            out.append(f"DISTSTYLE {style}")
        sortkeys = as_list(self.opt(table, "sortkeys"))
        kind = str(self.opt(table, "sortkey_type") or "COMPOUND").upper()
        if kind not in ("COMPOUND", "INTERLEAVED"):
            raise TargetConfigError(f"{table.name}: sortkey_type must be COMPOUND or INTERLEAVED")
        if len(sortkeys) > 8:
            raise TargetConfigError(
                f"{table.name}: at most 8 sort keys are supported here ({len(sortkeys)} given)"
            )
        if sortkeys:
            cols = ", ".join(self.q(self.column(table, s, "sort key").name) for s in sortkeys)
            out.append(f"{kind} SORTKEY ({cols})")
        else:
            out.append("SORTKEY AUTO")
        out.append("ENCODE AUTO")
        return "\n".join(out) + ";"
