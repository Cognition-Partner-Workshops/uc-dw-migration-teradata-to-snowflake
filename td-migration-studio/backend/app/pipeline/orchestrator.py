"""Run orchestration: per-table extract -> transform -> load -> validate on a background thread pool.

State lives in the control store, so a run can be resumed (passed tables skipped, failed tables restart
from the last durable stage) and re-running a table never duplicates rows (targets load with REPLACE).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..connectors import registry
from ..contracts.models import (
    MigrationPlan,
    ObjectState,
    ProfileSpec,
    Run,
    RunStatus,
    Stage,
    TablePlan,
    TargetMeta,
    TdBaseType,
)
from ..contracts.source import SourceConnector
from .control import ControlStore, ObjectRecord, utcnow
from .dq import ColumnDQ, OrphanResult, evaluate, orphan_count, profile_parquet
from .governance import masking_salt
from .options import resolve_target_config
from .planner import TargetFactory, default_target_factory
from .report import build_report
from .staging import extract_table, files_bytes, parquet_files, table_paths
from .transforms import build_specs, target_schema, transform_files

log = logging.getLogger(__name__)
NUMERIC_TYPES = {
    TdBaseType.BYTEINT,
    TdBaseType.SMALLINT,
    TdBaseType.INTEGER,
    TdBaseType.BIGINT,
    TdBaseType.DECIMAL,
    TdBaseType.NUMBER,
    TdBaseType.FLOAT,
}
ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


class RunConflict(RuntimeError):
    pass


class InjectedFailure(RuntimeError):
    pass


class DQFailed(RuntimeError):
    pass


def topo_order(tables: list[TablePlan]) -> list[TablePlan]:
    """Parents before children (soft RI); ties and cycles keep plan order."""
    by_name = {t.name.upper(): t for t in tables}
    deps = {
        t.name.upper(): {fk.ref_table.upper() for fk in t.source.foreign_keys}
        & set(by_name) - {t.name.upper()}
        for t in tables
    }
    out: list[TablePlan] = []
    done: set[str] = set()
    while len(out) < len(tables):
        ready = [t for t in tables if t.name.upper() not in done and deps[t.name.upper()] <= done]
        nxt = ready[0] if ready else next(t for t in tables if t.name.upper() not in done)
        out.append(nxt)
        done.add(nxt.name.upper())
    return out


def definition_hash(tp: TablePlan) -> str:
    payload = {
        "cols": [(c.target_name, c.effective_type, c.pii.masking if c.pii else "none") for c in tp.columns],
        "options": tp.target_options,
        "ddl": tp.ddl,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class RunContext:
    run_id: str
    plan: MigrationPlan
    meta: TargetMeta
    target_config: dict[str, Any]
    ready: dict[str, threading.Event] = field(default_factory=dict)
    position: dict[str, int] = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        repo: ControlStore,
        data_dir: Path,
        source_factory: Callable[[], SourceConnector] | None = None,
        target_factory: TargetFactory = default_target_factory,
        meta_lookup: Callable[[str], TargetMeta] = registry.get_target_meta,
        backoff_s: float = 1.0,
        ri_wait_s: float = 3600.0,
    ):
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.source_factory = source_factory or registry.get_source_connector
        self.target_factory = target_factory
        self.meta_lookup = meta_lookup
        self.backoff_s = backoff_s
        self.ri_wait_s = ri_wait_s
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    # public API ----------------------------------------------------------------------------------
    def start(self, plan: MigrationPlan) -> Run:
        if plan.status != "approved":
            raise RunConflict("plan must be approved before it can run")
        run = Run(
            id=f"run_{uuid.uuid4().hex[:12]}",
            plan_id=plan.id,
            target_id=plan.request.target_id,
            target_mode=plan.request.target_mode,
            status=RunStatus.QUEUED,
            created_at=utcnow(),
            objects=[
                ObjectState(table=t.name, target_table=f"{t.target_container}.{t.target_table}")
                for t in plan.tables
            ],
        )
        self.repo.create_run(run)
        self.repo.add_event(run.id, "run", f"Run created for plan {plan.id}", data={"status": "queued"})
        return self._launch(run.id, plan, force=set())

    def resume(self, run_id: str) -> Run:
        return self._launch(run_id, self._plan_for(run_id), force=set())

    def retry(self, run_id: str, tables: list[str]) -> Run:
        plan = self._plan_for(run_id)
        names = {t.name.upper(): t.name for t in plan.tables}
        unknown = [t for t in tables if t.upper() not in names]
        if unknown:
            raise KeyError(f"unknown table(s) {unknown}")
        force = {names[t.upper()] for t in tables} or {t.name for t in plan.tables}
        return self._launch(run_id, plan, force=force, only=force)

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            t = self._threads.get(run_id)
            return bool(t and t.is_alive())

    def wait(self, run_id: str, timeout: float | None = None) -> None:
        with self._lock:
            t = self._threads.get(run_id)
        if t:
            t.join(timeout)

    # internals ----------------------------------------------------------------------------------
    def _plan_for(self, run_id: str) -> MigrationPlan:
        run = self.repo.get_run(run_id)
        if run is None:
            raise KeyError(f"run '{run_id}' not found")
        plan = self.repo.get_plan(run.plan_id)
        if plan is None:
            raise KeyError(f"plan '{run.plan_id}' not found")
        return plan

    def _launch(self, run_id: str, plan: MigrationPlan, force: set[str], only: set[str] | None = None) -> Run:
        with self._lock:
            t = self._threads.get(run_id)
            if t and t.is_alive():
                raise RunConflict(f"run '{run_id}' is already running")
            self.repo.update_run(run_id, status=RunStatus.RUNNING, finished_at=None)
            t = threading.Thread(
                target=self._execute, args=(run_id, plan, force, only), daemon=True, name=f"run-{run_id}"
            )
            self._threads[run_id] = t
            t.start()
        return self.repo.get_run(run_id)  # type: ignore[return-value]

    def _event(
        self, ctx: RunContext, kind: str, msg: str, table: str | None = None, level: str = "info", **data: Any
    ) -> None:
        self.repo.add_event(ctx.run_id, kind, msg, level=level, table=table, data=data)

    def _execute(self, run_id: str, plan: MigrationPlan, force: set[str], only: set[str] | None) -> None:
        meta = self.meta_lookup(plan.request.target_id)
        ctx = RunContext(run_id, plan, meta, resolve_target_config(meta, plan.request.target_config))
        opts = plan.request.options
        try:
            run = self.repo.get_run(run_id)
            if run and run.started_at is None:
                self.repo.update_run(run_id, started_at=utcnow())
            ordered = topo_order(plan.tables)
            ctx.position = {t.name: i for i, t in enumerate(ordered)}
            ctx.ready = {t.name: threading.Event() for t in ordered}
            todo = []
            for tp in ordered:
                rec = self.repo.get_object(run_id, tp.name)
                skip = (only is not None and tp.name not in only) or (
                    rec is not None and rec.stage == Stage.PASSED and tp.name not in force
                )
                if skip:
                    ctx.ready[tp.name].set()
                    if rec is not None and rec.stage == Stage.PASSED:
                        self._event(ctx, "log", f"{tp.name}: already passed, skipped", tp.name)
                else:
                    todo.append(tp)
            self._event(
                ctx,
                "run",
                f"Run started: {len(todo)} table(s), parallelism {opts.parallelism}",
                status="running",
                tables=[t.name for t in todo],
            )
            with ThreadPoolExecutor(
                max_workers=max(1, opts.parallelism), thread_name_prefix=f"{run_id}-w"
            ) as pool:
                for f in [pool.submit(self._process_table, ctx, tp) for tp in todo]:
                    f.result()
            objs = self.repo.get_objects(run_id)
            passed = sum(1 for o in objs if o.stage == Stage.PASSED)
            status = (
                RunStatus.SUCCEEDED
                if passed == len(objs)
                else RunStatus.PARTIAL
                if passed
                else RunStatus.FAILED
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("run %s crashed", run_id)
            self._event(ctx, "log", f"Run crashed: {exc}", level="error")
            status = RunStatus.FAILED
        self.repo.update_run(run_id, status=status, finished_at=utcnow())
        try:
            run = self.repo.get_run(run_id)
            report = build_report(self.repo, run, plan, self.data_dir)  # type: ignore[arg-type]
            self.repo.save_report(run_id, report)
            t = report.totals
            self._event(
                ctx,
                "run",
                f"Run {status.value}: {t.passed}/{t.tables} tables passed, "
                f"{t.rows_loaded:,} rows loaded, {t.checks_passed}/{t.checks_total} checks passed",
                level="info" if status == RunStatus.SUCCEEDED else "warning",
                status=status.value,
                totals=t.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("report for run %s failed", run_id)
            self._event(
                ctx, "run", f"Run {status.value} (report failed: {exc})", level="error", status=status.value
            )

    # per table ----------------------------------------------------------------------------------
    def _process_table(self, ctx: RunContext, tp: TablePlan) -> None:
        max_attempts = max(1, ctx.plan.request.options.max_attempts)
        for n in range(1, max_attempts + 1):
            rec = self.repo.get_object(ctx.run_id, tp.name)
            attempt = (rec.attempts if rec else 0) + 1
            self.repo.update_object(
                ctx.run_id,
                tp.name,
                attempts=attempt,
                error=None,
                finished_at=None,
                started_at=(rec.started_at if rec and rec.started_at else utcnow()),
            )
            try:
                self._attempt(ctx, tp, attempt)
                return
            except DQFailed as exc:
                self._fail(ctx, tp, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                log.info("table %s attempt %s failed: %s", tp.name, attempt, exc)
                self._event(
                    ctx,
                    "log",
                    f"{tp.name}: attempt {attempt} failed: {exc}",
                    tp.name,
                    level="error",
                    attempt=attempt,
                )
                if n >= max_attempts:
                    self._fail(ctx, tp, f"{type(exc).__name__}: {exc}")
                    return
                delay = self.backoff_s * 2 ** (n - 1)
                self._event(
                    ctx,
                    "log",
                    f"{tp.name}: retrying in {delay:.1f}s ({n}/{max_attempts})",
                    tp.name,
                    level="warning",
                    delay_s=delay,
                )
                time.sleep(delay)

    def _fail(self, ctx: RunContext, tp: TablePlan, error: str) -> None:
        self._stage(ctx, tp, Stage.FAILED, error=error, finished_at=utcnow(), level="error")
        ctx.ready[tp.name].set()

    def _stage(
        self, ctx: RunContext, tp: TablePlan, stage: Stage, level: str = "info", **fields: Any
    ) -> None:
        self.repo.update_object(ctx.run_id, tp.name, stage=stage, **fields)
        msg = f"{tp.name}: {stage.value}" + (f" ({fields['error']})" if fields.get("error") else "")
        self._event(ctx, "state", msg, tp.name, level=level, stage=stage.value)

    def _inject(self, ctx: RunContext, tp: TablePlan, stage: str, attempt: int) -> None:
        for inj in ctx.plan.request.options.inject_failures:
            if inj.table.upper() == tp.name.upper() and inj.stage == stage and attempt <= inj.times:
                raise InjectedFailure(
                    f"injected failure at {stage} (attempt {attempt} of {inj.times} injected)"
                )

    def _timed(self, ctx: RunContext, tp: TablePlan, stage: str, started: float) -> None:
        rec = self.repo.get_object(ctx.run_id, tp.name)
        timings = dict(rec.stage_timings_s if rec else {})
        timings[stage] = round(timings.get(stage, 0.0) + time.monotonic() - started, 3)
        self.repo.update_object(ctx.run_id, tp.name, stage_timings_s=timings)

    def _attempt(self, ctx: RunContext, tp: TablePlan, attempt: int) -> None:
        rec = self.repo.get_object(ctx.run_id, tp.name)
        assert rec is not None
        paths = table_paths(self.data_dir, ctx.run_id, tp.name)
        raw_files = parquet_files(paths.raw)
        if not (rec.staged_path and rec.source_profile and raw_files):
            rec = self._extract(ctx, tp, attempt)
            raw_files = parquet_files(paths.raw)
        else:
            self._event(
                ctx,
                "log",
                f"{tp.name}: resuming from staged Parquet ({rec.rows_extracted:,} rows); extract skipped",
                tp.name,
                resumed=True,
            )

        # transform ------------------------------------------------------------------------------
        t0 = time.monotonic()
        self._stage(ctx, tp, Stage.TRANSFORMING)
        self._inject(ctx, tp, "transforming", attempt)
        specs = build_specs(tp, ctx.meta)
        res = transform_files(
            raw_files,
            specs,
            paths.transformed,
            paths.rejects,
            masking_salt(),
            ctx.plan.request.options.batch_rows,
        )
        schema = target_schema(specs)
        cols = self._dq_columns(tp, specs, res.touched)
        keys = self._target_keys(tp)
        staged_spec = ProfileSpec(
            numeric_columns=[c.target for c in cols if c.numeric],
            null_columns=[c.target for c in cols],
            checksum_columns=[c.target for c in cols] if ctx.plan.request.dq.checksum else [],
            unique_keys=keys,
        )
        staged_profile = profile_parquet(res.files, schema, staged_spec)
        self.repo.update_object(
            ctx.run_id,
            tp.name,
            rows_staged=res.rows_out,
            rows_rejected=res.rows_rejected,
            staged_profile=staged_profile,
        )
        ctx.ready[tp.name].set()
        lossy = {k: v for k, v in res.lossy.items()}
        self._event(
            ctx,
            "log",
            f"{tp.name}: transformed {res.rows_in:,} rows -> {res.rows_out:,} staged, "
            f"{res.rows_rejected:,} rejected",
            tp.name,
            level="warning" if res.rows_rejected else "info",
            rows_out=res.rows_out,
            rejected=res.rows_rejected,
            lossy=lossy,
            reject_reasons=dict(res.reject_reasons),
            masked=[s.target for s in specs if s.masking != "none"],
        )
        self._timed(ctx, tp, "transforming", t0)

        # load -----------------------------------------------------------------------------------
        t0 = time.monotonic()
        self._stage(ctx, tp, Stage.LOADING)
        req = ctx.plan.request
        target = self.target_factory(req.target_id, req.target_mode, req.target_connection, ctx.target_config)
        try:
            target.ensure_container(tp.target_container)
            target.create_table(tp)
            self._event(
                ctx,
                "log",
                f"{tp.name}: table ready ({tp.load_method or 'default'} load)",
                tp.name,
                ddl=tp.ddl,
            )
            load_id = f"{ctx.run_id}_a{attempt}"
            result = target.load(tp, res.files, load_id)
            self._inject(ctx, tp, "loading", attempt)
            mb = res.bytes / 1e6
            rate = result.rows_loaded / result.duration_s if result.duration_s else 0.0
            self._stage(ctx, tp, Stage.LOADED, rows_loaded=result.rows_loaded, load_id=load_id)
            self._event(
                ctx,
                "log",
                f"{tp.name}: loaded {result.rows_loaded:,} rows ({mb:.1f} MB) in "
                f"{result.duration_s:.2f}s, {rate:,.0f} rows/s via {result.method}",
                tp.name,
                rows=result.rows_loaded,
                mb=round(mb, 2),
                rows_per_s=round(rate, 1),
                method=result.method,
                details=result.details,
            )
            self.repo.upsert_registry(
                {
                    "target_id": req.target_id,
                    "target_mode": req.target_mode,
                    "target_table": f"{tp.target_container}.{tp.target_table}",
                    "source_table": tp.source.fqn,
                    "definition_hash": definition_hash(tp),
                    "last_run_id": ctx.run_id,
                    "last_load_id": load_id,
                    "row_count": result.rows_loaded,
                    "checksum": staged_profile.checksum,
                }
            )
            self._timed(ctx, tp, "loading", t0)

            # validate -------------------------------------------------------------------------------
            t0 = time.monotonic()
            self._stage(ctx, tp, Stage.VALIDATING)
            self._inject(ctx, tp, "validating", attempt)
            target_profile = target.profile(tp, staged_spec)
        finally:
            target.close()
        orphans = self._orphans(ctx, tp, res.files, schema) if req.dq.referential_integrity else []
        src_profile = rec.source_profile
        assert src_profile is not None
        checks = evaluate(
            cols, keys, src_profile, staged_profile, target_profile, res.rows_rejected, orphans, req.dq
        )
        self.repo.save_checks(ctx.run_id, tp.name, checks)
        self.repo.update_object(ctx.run_id, tp.name, target_profile=target_profile)
        failed = [c for c in checks if not c.passed]
        self._event(
            ctx,
            "log",
            f"{tp.name}: {len(checks) - len(failed)}/{len(checks)} checks passed",
            tp.name,
            level="warning" if failed else "info",
            failed=[f"{c.name}:{c.column or ''}" for c in failed],
        )
        self._timed(ctx, tp, "validating", t0)
        if failed:
            names = ", ".join(sorted({c.name + (f"({c.column})" if c.column else "") for c in failed}))
            raise DQFailed(f"DQ checks failed: {names}")
        self._stage(ctx, tp, Stage.PASSED, finished_at=utcnow())

    def _extract(self, ctx: RunContext, tp: TablePlan, attempt: int) -> ObjectRecord:
        t0 = time.monotonic()
        paths = table_paths(self.data_dir, ctx.run_id, tp.name)
        self._stage(ctx, tp, Stage.EXTRACTING, staged_path=None, source_profile=None, rows_extracted=0)
        est = tp.estimated_rows or 0
        source = self.source_factory()
        try:

            def on_batch(rows: int, batches: int) -> None:
                el = max(time.monotonic() - t0, 1e-6)
                self.repo.update_object(ctx.run_id, tp.name, rows_extracted=rows)
                self._event(
                    ctx,
                    "progress",
                    f"{tp.name}: extracted {rows:,} rows",
                    tp.name,
                    rows=rows,
                    pct=round(min(rows / est, 1.0) * 100, 1) if est else None,
                    rows_per_s=round(rows / el),
                )
                if batches == 1:
                    self._inject(ctx, tp, "extracting", attempt)

            ex = extract_table(source, tp, paths.raw, ctx.plan.request.options.batch_rows, on_batch)
            if ex.batches == 0:
                self._inject(ctx, tp, "extracting", attempt)
            cols = [c.source for c in tp.columns]
            spec = ProfileSpec(
                numeric_columns=[c.name for c in cols if c.base_type in NUMERIC_TYPES],
                null_columns=[c.name for c in cols],
            )
            profile = source.profile(tp.source.database, tp.source.name, spec)
        finally:
            source.close()
        el = max(time.monotonic() - t0, 1e-6)
        self._stage(
            ctx,
            tp,
            Stage.STAGED,
            staged_path=str(paths.root),
            source_profile=profile,
            rows_extracted=ex.rows,
            bytes_staged=files_bytes(ex.files),
        )
        self._event(
            ctx,
            "log",
            f"{tp.name}: extracted {ex.rows:,} rows ({ex.bytes / 1e6:.1f} MB) in {el:.2f}s, "
            f"{ex.rows / el:,.0f} rows/s; source count {profile.row_count:,}",
            tp.name,
            rows=ex.rows,
            mb=round(ex.bytes / 1e6, 2),
            rows_per_s=round(ex.rows / el, 1),
        )
        self._timed(ctx, tp, "extracting", t0)
        return self.repo.get_object(ctx.run_id, tp.name)  # type: ignore[return-value]

    @staticmethod
    def _dq_columns(tp: TablePlan, specs: list, touched: set[str]) -> list[ColumnDQ]:
        from .arrow_types import is_numeric

        out = []
        for c, s in zip(tp.columns, specs, strict=True):
            numeric = c.source.base_type in NUMERIC_TYPES and is_numeric(s.arrow_type)
            out.append(ColumnDQ(c.source.name, c.target_name, numeric, s.target in touched or c.overridden))
        return out

    @staticmethod
    def _target_keys(tp: TablePlan) -> list[list[str]]:
        m = {c.source.name.upper(): c.target_name for c in tp.columns}
        return [
            [m[k.upper()] for k in key] for key in tp.source.unique_keys if all(k.upper() in m for k in key)
        ]

    def _orphans(
        self, ctx: RunContext, tp: TablePlan, child_files: list[Path], child_schema
    ) -> list[OrphanResult]:
        out = []
        tables = {t.name.upper(): t for t in ctx.plan.tables}
        cmap = {c.source.name.upper(): c.target_name for c in tp.columns}
        for fk in tp.source.foreign_keys:
            parent = tables.get(fk.ref_table.upper())
            if parent is None or parent.name == tp.name:
                continue
            ev = ctx.ready.get(parent.name)
            if ev and ctx.position.get(parent.name, 0) < ctx.position.get(tp.name, 0):
                ev.wait(self.ri_wait_s)
            pfiles = parquet_files(table_paths(self.data_dir, ctx.run_id, parent.name).transformed)
            if not pfiles:
                self._event(
                    ctx,
                    "log",
                    f"{tp.name}: RI vs {parent.name} skipped (parent not staged)",
                    tp.name,
                    level="warning",
                )
                continue
            pmap = {c.source.name.upper(): c.target_name for c in parent.columns}
            ccols = [cmap[c.upper()] for c in fk.columns]
            pcols = [pmap[c.upper()] for c in fk.ref_columns]
            pschema = target_schema(build_specs(parent, ctx.meta))
            total, n, sample = orphan_count(child_files, child_schema, ccols, pfiles, pschema, pcols)
            out.append(OrphanResult(fk, ccols, parent.name, total, n, sample))
        return out
