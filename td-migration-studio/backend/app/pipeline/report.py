"""Build the RunReport (Results screen) and its CSV export from control-store state."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ..contracts.models import (
    MigrationPlan,
    Run,
    RunReport,
    RunTotals,
    Stage,
    TableReconciliation,
)
from .control import ControlStore, utcnow
from .staging import read_rejects, table_paths

REJECTS_SAMPLE = 5


def build_report(repo: ControlStore, run: Run, plan: MigrationPlan, data_dir: Path) -> RunReport:
    checks = repo.list_checks(run.id)
    records = {o.table: o for o in repo.get_objects(run.id)}
    tables: list[TableReconciliation] = []
    for tp in plan.tables:
        rec = records.get(tp.name)
        if rec is None:
            continue
        status = rec.stage.value if rec.stage in (Stage.PASSED, Stage.FAILED) else "skipped"
        src, stg, tgt = rec.source_profile, rec.staged_profile, rec.target_profile
        sample, _ = read_rejects(table_paths(data_dir, run.id, tp.name).rejects, REJECTS_SAMPLE)
        tables.append(
            TableReconciliation(
                table=tp.name,
                target_table=rec.target_table,
                status=status,  # type: ignore[arg-type]
                source_rows=src.row_count if src else rec.rows_extracted,
                staged_rows=rec.rows_staged,
                rejected_rows=rec.rows_rejected,
                target_rows=tgt.row_count if tgt else rec.rows_loaded,
                source_checksum=stg.checksum if stg else None,
                target_checksum=tgt.checksum if tgt else None,
                checksum_match=(stg.checksum == tgt.checksum)
                if stg and tgt and stg.checksum and tgt.checksum
                else None,
                checks=checks.get(tp.name, []),
                duration_s=round(sum(rec.stage_timings_s.values()), 3) if rec.stage_timings_s else None,
                rejects_sample=sample,
            )
        )
    start, end = run.started_at, run.finished_at or utcnow()
    duration = (end - start).total_seconds() if start else 0.0
    rows_loaded = sum(t.target_rows for t in tables)
    all_checks = [c for t in tables for c in t.checks]
    pii = [
        {
            "table": t.name,
            "column": c.target_name,
            "category": c.pii.category,
            "masking": c.pii.masking,
            "confidence": c.pii.confidence,
            "reason": c.pii.reason,
        }
        for t in plan.tables
        for c in t.columns
        if c.pii
    ]
    return RunReport(
        run_id=run.id,
        plan_id=plan.id,
        target_id=plan.target.id,
        target_display_name=plan.target.display_name,
        target_mode=run.target_mode,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        totals=RunTotals(
            tables=len(tables),
            passed=sum(1 for t in tables if t.status == "passed"),
            failed=sum(1 for t in tables if t.status == "failed"),
            rows_source=sum(t.source_rows for t in tables),
            rows_loaded=rows_loaded,
            rows_rejected=sum(t.rejected_rows for t in tables),
            bytes_staged=sum(o.bytes_staged for o in records.values()),
            duration_s=round(duration, 3),
            throughput_rows_per_s=round(rows_loaded / duration, 1) if duration > 0 else 0.0,
            checks_total=len(all_checks),
            checks_passed=sum(1 for c in all_checks if c.passed),
        ),
        tables=tables,
        governance={
            "pii_columns": pii,
            "masked_columns": sum(1 for p in pii if p["masking"] != "none"),
            "notes": plan.governance_notes,
            "options": plan.request.governance.model_dump(),
            "access_script": bool(plan.access_script),
        },
        thresholds=plan.request.dq.thresholds,
    )


CSV_COLUMNS = [
    "table",
    "target_table",
    "status",
    "source_rows",
    "staged_rows",
    "rejected_rows",
    "target_rows",
    "source_checksum",
    "target_checksum",
    "checksum_match",
    "checks_passed",
    "checks_total",
    "failed_checks",
    "duration_s",
]


def report_csv(report: RunReport) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for t in report.tables:
        failed = [f"{c.name}{'(' + c.column + ')' if c.column else ''}" for c in t.checks if not c.passed]
        w.writerow(
            [
                t.table,
                t.target_table,
                t.status,
                t.source_rows,
                t.staged_rows,
                t.rejected_rows,
                t.target_rows,
                t.source_checksum or "",
                t.target_checksum or "",
                "" if t.checksum_match is None else t.checksum_match,
                sum(1 for c in t.checks if c.passed),
                len(t.checks),
                " ".join(failed),
                t.duration_s or "",
            ]
        )
    return buf.getvalue()
