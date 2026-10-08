"""PlanRequest -> MigrationPlan: describe, map types, name, classify PII, resolve options, render DDL."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

import pyarrow as pa

from .. import typemap
from ..connectors import registry
from ..contracts.models import (
    ColumnMeta,
    ColumnOverride,
    ColumnPlan,
    MappingDecision,
    MigrationPlan,
    PiiTag,
    PlanRequest,
    PlanWarning,
    TableMeta,
    TablePlan,
    TargetMeta,
    TargetSummary,
    TdBaseType,
)
from ..contracts.source import SourceConnector
from ..contracts.target import TargetConnector
from .control import utcnow
from .governance import HASH_HEX_LEN, TEXT_TYPES, classify_table, governance_notes
from .identifiers import normalize_identifier
from .options import resolve_table_options, resolve_target_config

SourceFactory = Callable[[], SourceConnector]
TargetFactory = Callable[[str, str, dict[str, Any], dict[str, Any]], TargetConnector]
SAMPLE_ROWS = 300


class PlanError(ValueError):
    pass


def default_target_factory(
    target_id: str, mode: str, connection: dict[str, Any], config: dict[str, Any]
) -> TargetConnector:
    return registry.get_target_connector(target_id, mode, connection, config)


def masked_column_meta(col: ColumnMeta, masking: str) -> ColumnMeta | None:
    """Masked values are text; describe the column the target must store instead (None = unchanged)."""
    if masking == "hash":
        length = HASH_HEX_LEN
    elif masking == "partial" and col.base_type not in TEXT_TYPES:
        length = 40
    else:
        return None
    return col.model_copy(
        update={
            "base_type": TdBaseType.VARCHAR,
            "td_type": f"VARCHAR({length}) CHARACTER SET LATIN",
            "td_type_code": "CV",
            "length": length,
            "charset": "LATIN",
            "precision": None,
            "scale": None,
            "fractional_seconds": None,
        }
    )


def map_column(meta: TargetMeta, col: ColumnMeta, pii: PiiTag | None) -> MappingDecision:
    try:
        decision = typemap.resolve_type(meta, col)
    except Exception as exc:  # noqa: BLE001 - surfaced as a plan error
        return MappingDecision(target_type="", severity="error", reason=f"no type mapping: {exc}")
    masked = masked_column_meta(col, pii.masking) if pii else None
    if masked is not None:
        m = typemap.resolve_type(meta, masked)
        return m.model_copy(
            update={"reason": f"{pii.masking}-masked text (unmasked type: {decision.target_type})"}  # type: ignore[union-attr]
        )
    return decision


def target_summary(meta: TargetMeta, mode: str) -> TargetSummary:
    for s in registry.target_summaries():
        if s.id == meta.id:
            return s
    return TargetSummary(
        id=meta.id,
        display_name=meta.display_name,
        vendor=meta.vendor,
        modes=[mode],  # type: ignore[list-item]
        real_ready=registry.real_ready(meta),
        free_tier_note=meta.free_tier_note,
    )


def _sample(source: SourceConnector, table: TableMeta, rows: int) -> pa.Table | None:
    cols = [c.name for c in table.columns if c.base_type in TEXT_TYPES]
    if not cols or rows <= 0:
        return None
    it = source.extract(table.database, table.name, columns=cols, batch_rows=rows)
    try:
        first = next(iter(it), None)
    finally:
        close = getattr(it, "close", None)
        if close:
            close()
    return pa.Table.from_batches([first]).slice(0, rows) if first is not None else None


class Planner:
    def __init__(
        self,
        source_factory: SourceFactory | None = None,
        target_factory: TargetFactory = default_target_factory,
        meta_lookup: Callable[[str], TargetMeta] = registry.get_target_meta,
        sample_rows: int = SAMPLE_ROWS,
    ):
        self.source_factory = source_factory or registry.get_source_connector
        self.target_factory = target_factory
        self.meta_lookup = meta_lookup
        self.sample_rows = sample_rows

    def connector_for(self, plan_or_req: MigrationPlan | PlanRequest) -> TargetConnector:
        req = plan_or_req.request if isinstance(plan_or_req, MigrationPlan) else plan_or_req
        meta = self.meta_lookup(req.target_id)
        return self.target_factory(
            req.target_id,
            req.target_mode,
            req.target_connection,
            resolve_target_config(meta, req.target_config),
        )

    # ------------------------------------------------------------------------------------------
    def create(self, req: PlanRequest) -> MigrationPlan:
        meta = self.meta_lookup(req.target_id)
        source = self.source_factory()
        try:
            names = req.tables or [t.name for t in source.list_tables(req.source_database)]
            if not names:
                raise PlanError(f"no tables found in {req.source_database}")
            tables = [
                self._table_plan(source, meta, req, source.describe_table(req.source_database, n))
                for n in names
            ]
        finally:
            source.close()
        plan = MigrationPlan(
            id=f"plan_{uuid.uuid4().hex[:12]}",
            created_at=utcnow(),
            request=req,
            target=target_summary(meta, req.target_mode),
            tables=tables,
        )
        return self.finalize(plan)

    def _table_plan(
        self, source: SourceConnector, meta: TargetMeta, req: PlanRequest, table: TableMeta
    ) -> TablePlan:
        sample = None
        if req.governance.pii_classification:
            try:
                sample = _sample(source, table, self.sample_rows)
            except Exception:  # noqa: BLE001 - sampling is best effort; name rules still apply
                sample = None
        tags, _ = classify_table(table, sample, req.governance)
        columns = [
            ColumnPlan(
                source=c,
                target_name=normalize_identifier(c.name, meta.identifiers)[0],
                mapping=MappingDecision(target_type=""),
                pii=tags.get(c.name),
            )
            for c in sorted(table.columns, key=lambda c: c.ordinal)
        ]
        return TablePlan(
            source=table,
            target_container="",
            target_table=normalize_identifier(table.name, meta.identifiers)[0],
            columns=columns,
            estimated_rows=table.row_count,
        )

    # ------------------------------------------------------------------------------------------
    def apply_overrides(self, plan: MigrationPlan, overrides: list[ColumnOverride]) -> MigrationPlan:
        meta = self.meta_lookup(plan.request.target_id)
        plan = plan.model_copy(deep=True)
        by_table = {t.name.lower(): t for t in plan.tables} | {t.target_table.lower(): t for t in plan.tables}
        for ov in overrides:
            tp = by_table.get(ov.table.lower())
            if tp is None:
                raise PlanError(f"unknown table '{ov.table}'")
            cp = next(
                (
                    c
                    for c in tp.columns
                    if ov.column.lower() in (c.source.name.lower(), c.target_name.lower())
                ),
                None,
            )
            if cp is None:
                raise PlanError(f"unknown column '{ov.table}.{ov.column}'")
            if ov.target_type is not None:
                if ov.target_type.strip():
                    try:
                        typemap.target_type_info(meta, ov.target_type)
                    except Exception as exc:  # noqa: BLE001
                        raise PlanError(f"invalid target type '{ov.target_type}': {exc}") from exc
                    cp.override_type, cp.overridden = ov.target_type.strip(), True
                else:
                    cp.override_type, cp.overridden = None, False
            if ov.masking is not None:
                if cp.pii is None:
                    cp.pii = PiiTag(category="other", confidence=1.0, reason="manually classified")
                cp.pii.masking = ov.masking
                cp.overridden = True
        plan.status = "draft"
        return self.finalize(plan)

    def approve(self, plan: MigrationPlan) -> MigrationPlan:
        errors = [w for w in plan.warnings if w.severity == "error"]
        if errors:
            raise PlanError(f"plan has {len(errors)} error(s); fix with overrides first: {errors[0].message}")
        return plan.model_copy(update={"status": "approved"})

    # ------------------------------------------------------------------------------------------
    def finalize(self, plan: MigrationPlan) -> MigrationPlan:
        """(Re)compute mappings, options, DDL, warnings, summary and governance from the plan state."""
        req = plan.request
        meta = self.meta_lookup(req.target_id)
        target_values = resolve_target_config(meta, req.target_config)
        container = normalize_identifier(
            str(target_values.get(meta.container_label) or "retail_dw"), meta.identifiers
        )[0]
        connector = self.target_factory(req.target_id, req.target_mode, req.target_connection, target_values)
        in_scope = {t.name.upper() for t in plan.tables}
        warnings: list[PlanWarning] = []
        try:
            for tp in plan.tables:
                warnings += self._finalize_table(tp, meta, req, target_values, container, in_scope)
                try:
                    tp.ddl = connector.render_ddl(tp)
                except Exception as exc:  # noqa: BLE001
                    tp.ddl = ""
                    warnings.append(
                        PlanWarning(severity="error", table=tp.name, message=f"DDL render failed: {exc}")
                    )
            masked = {
                f"{t.name}.{c.source.name}": c.pii.masking
                for t in plan.tables
                for c in t.columns
                if c.pii and c.pii.masking != "none"
            }
            plan.governance_notes = governance_notes(meta, req.governance, masked)
            plan.warnings = warnings
            plan.summary = self._summary(plan)
            plan.access_script = connector.access_script(plan) if req.governance.access_roles else ""
        finally:
            connector.close()
        return plan

    def _finalize_table(
        self,
        tp: TablePlan,
        meta: TargetMeta,
        req: PlanRequest,
        target_values: dict[str, Any],
        container: str,
        in_scope: set[str],
    ) -> list[PlanWarning]:
        t = tp.name
        out: list[PlanWarning] = []

        def warn(sev: str, msg: str, col: str | None = None) -> None:
            out.append(PlanWarning(severity=sev, table=t, column=col, message=msg))  # type: ignore[arg-type]

        for note in normalize_identifier(t, meta.identifiers)[1]:
            warn("info", note)
        for cp in tp.columns:
            col = cp.source
            for note in normalize_identifier(col.name, meta.identifiers)[1]:
                warn("info", note, col.name)
            if cp.pii and cp.pii.masking == "nullify" and not col.nullable:
                cp.pii.masking = "hash"
                warn("warning", "NOT NULL column cannot be nullified; masking switched to hash", col.name)
            if cp.pii and not req.governance.masking:
                cp.pii.masking = "none"
            cp.mapping = map_column(meta, col, cp.pii)
            m = cp.mapping
            if m.severity == "error" and not cp.override_type:
                warn("error", f"{col.td_type}: {m.reason or 'unmapped type'}", col.name)
            elif m.lossy:
                warn(
                    m.severity,
                    f"lossy {col.td_type} -> {m.target_type}: {m.reason or 'precision loss'}",
                    col.name,
                )
            try:
                typemap.target_type_info(meta, cp.effective_type)
            except Exception as exc:  # noqa: BLE001
                warn("error", f"target type '{cp.effective_type}' not understood: {exc}", col.name)
            if cp.overridden and cp.override_type:
                warn("info", f"type overridden: {m.target_type} -> {cp.override_type}", col.name)
            if cp.pii:
                sev = "warning" if cp.pii.category == "free_text" and cp.pii.masking == "none" else "info"
                warn(
                    sev,
                    f"PII {cp.pii.category} ({cp.pii.confidence:.0%}): {cp.pii.reason}; "
                    f"masking={cp.pii.masking}",
                    col.name,
                )

        colmap = {c.source.name: c.target_name for c in tp.columns}
        tp.target_container = container
        tp.target_options, notes = resolve_table_options(
            meta,
            tp.source,
            colmap,
            target_values,
            req.table_config.get(t, req.table_config.get(t.lower(), {})),
        )
        tp.load_method = tp.target_options.get("load_method") or (
            meta.load_methods[0] if meta.load_methods else None
        )
        for n in notes:
            warn("info", n)
        if not tp.source.unique_keys:
            warn(
                "warning",
                "no unique key (UPI/USI/PK): uniqueness check skipped; duplicates cannot be detected",
            )
        for fk in tp.source.foreign_keys:
            if fk.ref_table.upper() not in in_scope:
                warn("info", f"referential integrity vs {fk.ref_table} skipped (parent table not in scope)")
        if tp.source.row_count is None:
            warn("info", "row count unknown (statistics missing)")
        return out

    @staticmethod
    def _summary(plan: MigrationPlan) -> dict[str, Any]:
        cols = [c for t in plan.tables for c in t.columns]
        sev = Counter(w.severity for w in plan.warnings)
        return {
            "tables": len(plan.tables),
            "columns": len(cols),
            "est_rows": sum(t.estimated_rows or 0 for t in plan.tables),
            "est_bytes": sum(t.source.size_bytes or 0 for t in plan.tables),
            "lossy_columns": sum(1 for c in cols if c.mapping.lossy),
            "pii_columns": sum(1 for c in cols if c.pii),
            "masked_columns": sum(1 for c in cols if c.pii and c.pii.masking != "none"),
            "overridden_columns": sum(1 for c in cols if c.overridden),
            "warnings": {k: sev.get(k, 0) for k in ("info", "warning", "error")},
            "type_mappings": dict(Counter(f"{c.source.base_type.value} -> {c.effective_type}" for c in cols)),
        }
