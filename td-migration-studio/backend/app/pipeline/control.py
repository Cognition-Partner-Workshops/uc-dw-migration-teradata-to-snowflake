"""Control repository over the `ctl` schema (plans, runs, run_objects, run_events, run_checks, registry).

`PgControlRepo` is the production store (psycopg3 pool); `MemoryControlRepo` implements the same interface
in-process for unit tests and offline experiments.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..contracts.models import (
    CheckResult,
    MigrationPlan,
    ObjectState,
    Run,
    RunEvent,
    RunReport,
    RunStatus,
    Stage,
    TableProfile,
)

DDL_PATH = Path(__file__).resolve().parent.parent / "control" / "ddl.sql"
TERMINAL_STAGES = {Stage.PASSED, Stage.FAILED, Stage.PENDING}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ObjectRecord(ObjectState):
    """ObjectState plus the durable artefacts the orchestrator needs to resume."""

    staged_path: str | None = None
    source_profile: TableProfile | None = None
    staged_profile: TableProfile | None = None
    target_profile: TableProfile | None = None
    load_id: str | None = None

    def public(self) -> ObjectState:
        return ObjectState.model_validate(self.model_dump(include=set(ObjectState.model_fields)))


_PROFILE_FIELDS = ("source_profile", "staged_profile", "target_profile")
_OBJECT_COLUMNS = {
    "stage": "stage",
    "attempts": "attempts",
    "rows_extracted": "rows_extracted",
    "rows_staged": "rows_staged",
    "rows_rejected": "rows_rejected",
    "rows_loaded": "rows_loaded",
    "bytes_staged": "bytes_staged",
    "staged_path": "staged_path",
    "source_profile": "source_profile",
    "staged_profile": "staged_profile",
    "target_profile": "target_profile",
    "load_id": "load_id",
    "error": "error",
    "stage_timings_s": "stage_timings",
    "started_at": "started_at",
    "finished_at": "finished_at",
}
_RUN_COLUMNS = {"status", "started_at", "finished_at", "resumed_from"}


def _progress(rec: ObjectRecord) -> float:
    weights = {
        Stage.PENDING: 0.0,
        Stage.EXTRACTING: 0.05,
        Stage.STAGED: 0.5,
        Stage.TRANSFORMING: 0.55,
        Stage.LOADING: 0.7,
        Stage.LOADED: 0.85,
        Stage.VALIDATING: 0.9,
        Stage.PASSED: 1.0,
        Stage.FAILED: 1.0,
    }
    return weights[rec.stage]


class ControlStore:
    """Interface shared by the Postgres and in-memory stores."""

    def init_schema(self) -> None: ...
    def save_plan(self, plan: MigrationPlan) -> None: ...
    def get_plan(self, plan_id: str) -> MigrationPlan | None: ...
    def create_run(self, run: Run) -> None: ...
    def get_run(self, run_id: str) -> Run | None: ...
    def list_runs(self) -> list[Run]: ...
    def update_run(self, run_id: str, **fields: Any) -> None: ...
    def get_objects(self, run_id: str) -> list[ObjectRecord]: ...
    def get_object(self, run_id: str, table: str) -> ObjectRecord | None: ...
    def update_object(self, run_id: str, table: str, **fields: Any) -> None: ...
    def add_event(self, run_id: str, kind: str, message: str, **kw: Any) -> RunEvent: ...
    def list_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[RunEvent]: ...
    def save_checks(self, run_id: str, table: str, checks: list[CheckResult]) -> None: ...
    def list_checks(self, run_id: str) -> dict[str, list[CheckResult]]: ...
    def save_report(self, run_id: str, report: RunReport) -> None: ...
    def get_report(self, run_id: str) -> RunReport | None: ...
    def upsert_registry(self, entry: dict[str, Any]) -> None: ...
    def list_registry(self) -> list[dict[str, Any]]: ...

    def mark_interrupted(self) -> list[str]:
        """Runs left queued/running by a dead process become resumable (failed + in-flight objects failed)."""
        ids = []
        for run in self.list_runs():
            if run.status not in (RunStatus.RUNNING, RunStatus.QUEUED):
                continue
            for obj in run.objects:
                if obj.stage not in TERMINAL_STAGES:
                    self.update_object(
                        run.id, obj.table, stage=Stage.FAILED, error="interrupted (API restart)"
                    )
            self.update_run(run.id, status=RunStatus.FAILED, finished_at=utcnow())
            self.add_event(
                run.id,
                "run",
                "Run interrupted by an API restart; POST /api/runs/{id}/resume to continue",
                level="warning",
                data={"status": RunStatus.FAILED.value, "resumable": True},
            )
            ids.append(run.id)
        return ids


def _check_key(c: CheckResult) -> tuple[str, str]:
    return c.name, c.column or ""


# --------------------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------------------


class PgControlRepo(ControlStore):
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 12, timeout: float = 30.0):
        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        self.pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self.pool.close()

    def _exec(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def init_schema(self) -> None:
        with self.pool.connection() as conn:
            conn.execute(DDL_PATH.read_text())

    # plans --------------------------------------------------------------------------------------
    def save_plan(self, plan: MigrationPlan) -> None:
        self._exec(
            """INSERT INTO ctl.plans (plan_id, created_at, status, target_id, target_mode, plan_json)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (plan_id) DO UPDATE
               SET status = EXCLUDED.status, plan_json = EXCLUDED.plan_json""",
            (
                plan.id,
                plan.created_at,
                plan.status,
                plan.request.target_id,
                plan.request.target_mode,
                Jsonb(plan.model_dump(mode="json")),
            ),
        )

    def get_plan(self, plan_id: str) -> MigrationPlan | None:
        rows = self._exec("SELECT plan_json FROM ctl.plans WHERE plan_id = %s", (plan_id,))
        return MigrationPlan.model_validate(rows[0]["plan_json"]) if rows else None

    # runs ---------------------------------------------------------------------------------------
    def create_run(self, run: Run) -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO ctl.runs (run_id, plan_id, target_id, target_mode, status, created_at,
                   resumed_from) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    run.id,
                    run.plan_id,
                    run.target_id,
                    run.target_mode,
                    run.status.value,
                    run.created_at,
                    run.resumed_from,
                ),
            )
            for o in run.objects:
                conn.execute(
                    "INSERT INTO ctl.run_objects (run_id, table_name, target_table) VALUES (%s, %s, %s)",
                    (run.id, o.table, o.target_table),
                )

    def _run_from_row(self, row: dict[str, Any], objects: list[ObjectRecord]) -> Run:
        pub = [o.public() for o in objects]
        return Run(
            id=row["run_id"],
            plan_id=row["plan_id"],
            target_id=row["target_id"],
            target_mode=row["target_mode"],
            status=RunStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            resumed_from=row["resumed_from"],
            objects=pub,
            progress=round(sum(o.progress for o in pub) / len(pub), 4) if pub else 0.0,
        )

    def get_run(self, run_id: str) -> Run | None:
        rows = self._exec("SELECT * FROM ctl.runs WHERE run_id = %s", (run_id,))
        return self._run_from_row(rows[0], self.get_objects(run_id)) if rows else None

    def list_runs(self) -> list[Run]:
        runs = self._exec("SELECT * FROM ctl.runs ORDER BY created_at DESC")
        objs = self._exec("SELECT * FROM ctl.run_objects ORDER BY run_id, table_name")
        by_run: dict[str, list[ObjectRecord]] = {}
        for o in objs:
            by_run.setdefault(o["run_id"], []).append(self._obj_from_row(o))
        return [self._run_from_row(r, by_run.get(r["run_id"], [])) for r in runs]

    def update_run(self, run_id: str, **fields: Any) -> None:
        bad = set(fields) - _RUN_COLUMNS
        if bad:
            raise ValueError(f"unknown run fields {bad}")
        if "status" in fields:
            fields["status"] = RunStatus(fields["status"]).value
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._exec(f"UPDATE ctl.runs SET {sets} WHERE run_id = %s", (*fields.values(), run_id))

    # objects ------------------------------------------------------------------------------------
    @staticmethod
    def _obj_from_row(r: dict[str, Any]) -> ObjectRecord:
        rec = ObjectRecord(
            table=r["table_name"],
            target_table=r["target_table"],
            stage=Stage(r["stage"]),
            attempts=r["attempts"],
            rows_extracted=r["rows_extracted"],
            rows_staged=r["rows_staged"],
            rows_rejected=r["rows_rejected"],
            rows_loaded=r["rows_loaded"],
            bytes_staged=r["bytes_staged"],
            started_at=r["started_at"],
            updated_at=r["updated_at"],
            finished_at=r["finished_at"],
            error=r["error"],
            stage_timings_s=r["stage_timings"] or {},
            staged_path=r["staged_path"],
            load_id=r["load_id"],
            **{k: TableProfile.model_validate(r[k]) if r[k] else None for k in _PROFILE_FIELDS},
        )
        rec.progress = _progress(rec)
        return rec

    def get_objects(self, run_id: str) -> list[ObjectRecord]:
        rows = self._exec("SELECT * FROM ctl.run_objects WHERE run_id = %s ORDER BY table_name", (run_id,))
        return [self._obj_from_row(r) for r in rows]

    def get_object(self, run_id: str, table: str) -> ObjectRecord | None:
        rows = self._exec(
            "SELECT * FROM ctl.run_objects WHERE run_id = %s AND table_name = %s", (run_id, table)
        )
        return self._obj_from_row(rows[0]) if rows else None

    def update_object(self, run_id: str, table: str, **fields: Any) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            if k not in _OBJECT_COLUMNS:
                raise ValueError(f"unknown object field {k}")
            if k in _PROFILE_FIELDS and v is not None:
                v = Jsonb(v.model_dump(mode="json"))
            elif k == "stage_timings_s":
                v = Jsonb(v)
            elif k == "stage":
                v = Stage(v).value
            cols.append(f"{_OBJECT_COLUMNS[k]} = %s")
            vals.append(v)
        cols.append("updated_at = now()")
        self._exec(
            f"UPDATE ctl.run_objects SET {', '.join(cols)} WHERE run_id = %s AND table_name = %s",
            (*vals, run_id, table),
        )

    # events -------------------------------------------------------------------------------------
    def add_event(
        self,
        run_id: str,
        kind: str,
        message: str,
        level: str = "info",
        table: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (run_id,))
            row = conn.execute(
                """INSERT INTO ctl.run_events (run_id, seq, kind, level, table_name, message, data)
                   SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s, %s, %s
                   FROM ctl.run_events WHERE run_id = %s
                   RETURNING seq, ts""",
                (run_id, kind, level, table, message, Jsonb(data or {}), run_id),
            ).fetchone()
        return RunEvent(
            seq=row["seq"],
            ts=row["ts"],
            run_id=run_id,
            kind=kind,
            level=level,
            table=table,
            message=message,
            data=data or {},
        )

    def list_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[RunEvent]:
        rows = self._exec(
            """SELECT * FROM ctl.run_events WHERE run_id = %s AND seq > %s ORDER BY seq LIMIT %s""",
            (run_id, after, limit),
        )
        return [
            RunEvent(
                seq=r["seq"],
                ts=r["ts"],
                run_id=run_id,
                kind=r["kind"],
                level=r["level"],
                table=r["table_name"],
                message=r["message"],
                data=r["data"] or {},
            )
            for r in rows
        ]

    # checks / report ----------------------------------------------------------------------------
    def save_checks(self, run_id: str, table: str, checks: list[CheckResult]) -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("DELETE FROM ctl.run_checks WHERE run_id = %s AND table_name = %s", (run_id, table))
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO ctl.run_checks (run_id, table_name, check_name, column_name, passed,
                       source_value, target_value, diff, threshold, detail)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    [
                        (
                            run_id,
                            table,
                            c.name,
                            c.column or "",
                            c.passed,
                            c.source_value,
                            c.target_value,
                            c.diff,
                            c.threshold,
                            c.detail,
                        )
                        for c in checks
                    ],
                )

    def list_checks(self, run_id: str) -> dict[str, list[CheckResult]]:
        rows = self._exec(
            "SELECT * FROM ctl.run_checks WHERE run_id = %s ORDER BY table_name, check_name, column_name",
            (run_id,),
        )
        out: dict[str, list[CheckResult]] = {}
        for r in rows:
            out.setdefault(r["table_name"], []).append(
                CheckResult(
                    name=r["check_name"],
                    column=r["column_name"] or None,
                    passed=r["passed"],
                    source_value=r["source_value"],
                    target_value=r["target_value"],
                    diff=r["diff"],
                    threshold=r["threshold"],
                    detail=r["detail"],
                )
            )
        return out

    def save_report(self, run_id: str, report: RunReport) -> None:
        self._exec(
            "UPDATE ctl.runs SET report_json = %s WHERE run_id = %s",
            (Jsonb(report.model_dump(mode="json")), run_id),
        )

    def get_report(self, run_id: str) -> RunReport | None:
        rows = self._exec("SELECT report_json FROM ctl.runs WHERE run_id = %s", (run_id,))
        return RunReport.model_validate(rows[0]["report_json"]) if rows and rows[0]["report_json"] else None

    def upsert_registry(self, entry: dict[str, Any]) -> None:
        self._exec(
            """INSERT INTO ctl.object_registry (target_id, target_mode, target_table, source_table,
               definition_hash, last_run_id, last_load_id, row_count, checksum, loaded_at)
               VALUES (%(target_id)s, %(target_mode)s, %(target_table)s, %(source_table)s,
                       %(definition_hash)s, %(last_run_id)s, %(last_load_id)s, %(row_count)s,
                       %(checksum)s, now())
               ON CONFLICT (target_id, target_mode, target_table) DO UPDATE SET
                 source_table = EXCLUDED.source_table, definition_hash = EXCLUDED.definition_hash,
                 last_run_id = EXCLUDED.last_run_id, last_load_id = EXCLUDED.last_load_id,
                 row_count = EXCLUDED.row_count, checksum = EXCLUDED.checksum, loaded_at = now()""",
            entry,
        )

    def list_registry(self) -> list[dict[str, Any]]:
        return self._exec("SELECT * FROM ctl.object_registry ORDER BY target_id, target_mode, target_table")


# --------------------------------------------------------------------------------------------------
# In-memory (tests)
# --------------------------------------------------------------------------------------------------


class MemoryControlRepo(ControlStore):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.plans: dict[str, MigrationPlan] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, dict[str, ObjectRecord]] = {}
        self.events: dict[str, list[RunEvent]] = {}
        self.checks: dict[str, dict[str, list[CheckResult]]] = {}
        self.reports: dict[str, RunReport] = {}
        self.registry: dict[tuple[str, str, str], dict[str, Any]] = {}

    def init_schema(self) -> None:
        return None

    def save_plan(self, plan: MigrationPlan) -> None:
        with self._lock:
            self.plans[plan.id] = plan.model_copy(deep=True)

    def get_plan(self, plan_id: str) -> MigrationPlan | None:
        with self._lock:
            p = self.plans.get(plan_id)
            return p.model_copy(deep=True) if p else None

    def create_run(self, run: Run) -> None:
        with self._lock:
            self.runs[run.id] = run.model_dump(exclude={"objects", "progress"})
            self.objects[run.id] = {
                o.table: ObjectRecord(table=o.table, target_table=o.target_table, updated_at=utcnow())
                for o in run.objects
            }
            self.events[run.id] = []

    def get_run(self, run_id: str) -> Run | None:
        with self._lock:
            row = self.runs.get(run_id)
            if row is None:
                return None
            objs = [o.public() for o in self.get_objects(run_id)]
            progress = round(sum(o.progress for o in objs) / len(objs), 4) if objs else 0.0
            return Run(**copy.deepcopy(row), objects=objs, progress=progress)

    def list_runs(self) -> list[Run]:
        with self._lock:
            runs = [self.get_run(r) for r in self.runs]
        return sorted([r for r in runs if r], key=lambda r: r.created_at, reverse=True)

    def update_run(self, run_id: str, **fields: Any) -> None:
        bad = set(fields) - _RUN_COLUMNS
        if bad:
            raise ValueError(f"unknown run fields {bad}")
        with self._lock:
            if "status" in fields:
                fields["status"] = RunStatus(fields["status"])
            self.runs[run_id].update(fields)

    def get_objects(self, run_id: str) -> list[ObjectRecord]:
        with self._lock:
            return [self.get_object(run_id, t) for t in sorted(self.objects.get(run_id, {}))]  # type: ignore[misc]

    def get_object(self, run_id: str, table: str) -> ObjectRecord | None:
        with self._lock:
            rec = self.objects.get(run_id, {}).get(table)
            if rec is None:
                return None
            rec = rec.model_copy(deep=True)
            rec.progress = _progress(rec)
            return rec

    def update_object(self, run_id: str, table: str, **fields: Any) -> None:
        bad = set(fields) - set(_OBJECT_COLUMNS)
        if bad:
            raise ValueError(f"unknown object field {bad}")
        with self._lock:
            rec = self.objects[run_id][table]
            for k, v in fields.items():
                setattr(rec, k, Stage(v) if k == "stage" else copy.deepcopy(v))
            rec.updated_at = utcnow()

    def add_event(
        self,
        run_id: str,
        kind: str,
        message: str,
        level: str = "info",
        table: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        with self._lock:
            evs = self.events.setdefault(run_id, [])
            ev = RunEvent(
                seq=len(evs) + 1,
                ts=utcnow(),
                run_id=run_id,
                kind=kind,
                level=level,
                table=table,
                message=message,
                data=data or {},
            )
            evs.append(ev)
            return ev

    def list_events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[RunEvent]:
        with self._lock:
            return [e for e in self.events.get(run_id, []) if e.seq > after][:limit]

    def save_checks(self, run_id: str, table: str, checks: list[CheckResult]) -> None:
        with self._lock:
            uniq = {_check_key(c): c for c in reversed(checks)}
            self.checks.setdefault(run_id, {})[table] = sorted(uniq.values(), key=_check_key)

    def list_checks(self, run_id: str) -> dict[str, list[CheckResult]]:
        with self._lock:
            return copy.deepcopy(self.checks.get(run_id, {}))

    def save_report(self, run_id: str, report: RunReport) -> None:
        with self._lock:
            self.reports[run_id] = report

    def get_report(self, run_id: str) -> RunReport | None:
        with self._lock:
            return self.reports.get(run_id)

    def upsert_registry(self, entry: dict[str, Any]) -> None:
        with self._lock:
            key = (entry["target_id"], entry["target_mode"], entry["target_table"])
            self.registry[key] = {**entry, "loaded_at": utcnow()}

    def list_registry(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.registry[k] for k in sorted(self.registry)]
