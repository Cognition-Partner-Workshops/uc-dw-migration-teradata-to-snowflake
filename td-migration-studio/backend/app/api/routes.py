"""Routes exactly as listed in CONTRACTS.md. Blocking work runs in FastAPI's threadpool (sync handlers)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from ..connectors import registry
from ..contracts.models import (
    ColumnOverride,
    ConnectionTestResult,
    MigrationPlan,
    PlanRequest,
    Run,
    RunReport,
    RunStatus,
    SourceTableSummary,
    TableMeta,
    TargetMeta,
    TargetSummary,
)
from ..pipeline.options import resolve_target_config
from ..pipeline.orchestrator import RunConflict
from ..pipeline.planner import PlanError
from ..pipeline.report import report_csv
from ..pipeline.staging import read_rejects, table_paths
from ..settings import get_settings
from .services import Services, get_services

router = APIRouter(prefix="/api")
Svc = Depends(get_services)
TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.PARTIAL}
POLL_S = 0.5


class TargetTestRequest(BaseModel):
    mode: Literal["simulated", "real"] = "simulated"
    connection: dict[str, Any] = {}


class StartRunRequest(BaseModel):
    plan_id: str


class RetryRequest(BaseModel):
    tables: list[str] = []


def _404(what: str, key: str) -> HTTPException:
    return HTTPException(404, f"{what} '{key}' not found")


def _plan(svc: Services, plan_id: str) -> MigrationPlan:
    plan = svc.repo.get_plan(plan_id)
    if plan is None:
        raise _404("plan", plan_id)
    return plan


def _run(svc: Services, run_id: str) -> Run:
    run = svc.repo.get_run(run_id)
    if run is None:
        raise _404("run", run_id)
    return run


def _source(svc: Services):
    return svc.planner.source_factory()


# health / source ---------------------------------------------------------------------------------
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/source/connection")
def source_connection() -> dict[str, Any]:
    s = get_settings()
    host = s.td_host if s.td_mode == "real" else urlparse(s.td_emu_dsn).hostname
    return {"mode": s.td_mode, "host": host, "database": s.td_database}


@router.post("/source/test")
def source_test(svc: Services = Svc) -> ConnectionTestResult:
    mode = "real" if get_settings().td_mode == "real" else "emulated"
    try:
        src = _source(svc)
        try:
            return src.test_connection()
        finally:
            src.close()
    except Exception as exc:  # noqa: BLE001 - reported to the UI, not raised
        return ConnectionTestResult(ok=False, mode=mode, message=f"{type(exc).__name__}: {exc}")


@router.get("/source/databases")
def source_databases(svc: Services = Svc) -> list[str]:
    src = _source(svc)
    try:
        return src.list_databases()
    finally:
        src.close()


@router.get("/source/tables")
def source_tables(database: str | None = None, svc: Services = Svc) -> list[SourceTableSummary]:
    src = _source(svc)
    try:
        return src.list_tables(database or get_settings().td_database)
    finally:
        src.close()


@router.get("/source/tables/{database}/{table}")
def source_table(database: str, table: str, svc: Services = Svc) -> TableMeta:
    src = _source(svc)
    try:
        return src.describe_table(database, table)
    except KeyError as exc:
        raise _404("table", f"{database}.{table}") from exc
    finally:
        src.close()


# targets -----------------------------------------------------------------------------------------
@router.get("/targets")
def targets() -> list[TargetSummary]:
    return registry.target_summaries()


@router.get("/targets/{target_id}")
def target(target_id: str, svc: Services = Svc) -> TargetMeta:
    try:
        return svc.planner.meta_lookup(target_id)
    except KeyError as exc:
        raise _404("target", target_id) from exc


@router.post("/targets/{target_id}/test")
def target_test(target_id: str, body: TargetTestRequest, svc: Services = Svc) -> ConnectionTestResult:
    meta = target(target_id, svc)
    try:
        conn = svc.planner.target_factory(
            target_id, body.mode, body.connection, resolve_target_config(meta, {})
        )
        try:
            return conn.test_connection()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResult(ok=False, mode=body.mode, message=f"{type(exc).__name__}: {exc}")


# plans -------------------------------------------------------------------------------------------
@router.post("/plans")
def create_plan(req: PlanRequest, svc: Services = Svc) -> MigrationPlan:
    try:
        plan = svc.planner.create(req)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc
    except PlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    svc.repo.save_plan(plan)
    return plan


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, svc: Services = Svc) -> MigrationPlan:
    return _plan(svc, plan_id)


@router.post("/plans/{plan_id}/overrides")
def plan_overrides(plan_id: str, overrides: list[ColumnOverride], svc: Services = Svc) -> MigrationPlan:
    try:
        plan = svc.planner.apply_overrides(_plan(svc, plan_id), overrides)
    except PlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    plan = plan.model_copy(update={"status": "draft"})
    svc.repo.save_plan(plan)
    return plan


@router.post("/plans/{plan_id}/approve")
def approve_plan(plan_id: str, svc: Services = Svc) -> MigrationPlan:
    try:
        plan = svc.planner.approve(_plan(svc, plan_id))
    except PlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    svc.repo.save_plan(plan)
    return plan


# runs --------------------------------------------------------------------------------------------
@router.post("/runs")
def start_run(body: StartRunRequest, svc: Services = Svc) -> Run:
    try:
        return svc.orchestrator.start(_plan(svc, body.plan_id))
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/runs")
def list_runs(svc: Services = Svc) -> list[Run]:
    return svc.repo.list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str, svc: Services = Svc) -> Run:
    return _run(svc, run_id)


@router.get("/runs/{run_id}/events", response_model=None)
async def run_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    accept: str = Header(""),
    last_event_id: str | None = Header(None),
    svc: Services = Svc,
):
    await run_in_threadpool(_run, svc, run_id)
    if "application/json" in accept and "text/event-stream" not in accept:
        return await run_in_threadpool(svc.repo.list_events, run_id, after, 100_000)
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))

    async def stream() -> AsyncIterator[dict[str, Any]]:
        seq = after
        while not await request.is_disconnected():
            events = await run_in_threadpool(svc.repo.list_events, run_id, seq, 500)
            for ev in events:
                seq = ev.seq
                yield {"event": "run_event", "id": str(ev.seq), "data": ev.model_dump_json()}
            if events:
                continue
            run = await run_in_threadpool(svc.repo.get_run, run_id)
            if run is None or (run.status in TERMINAL and not svc.orchestrator.is_active(run_id)):
                return
            await asyncio.sleep(POLL_S)

    return EventSourceResponse(stream(), ping=15)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str, svc: Services = Svc) -> Run:
    _run(svc, run_id)
    try:
        return svc.orchestrator.resume(run_id)
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, body: RetryRequest, svc: Services = Svc) -> Run:
    _run(svc, run_id)
    try:
        return svc.orchestrator.retry(run_id, body.tables)
    except KeyError as exc:
        raise HTTPException(422, str(exc).strip("'\"")) from exc
    except RunConflict as exc:
        raise HTTPException(409, str(exc)) from exc


def _report(svc: Services, run_id: str) -> RunReport:
    _run(svc, run_id)
    report = svc.repo.get_report(run_id)
    if report is None:
        raise HTTPException(404, f"report for run '{run_id}' not available yet")
    return report


@router.get("/runs/{run_id}/report")
def run_report(run_id: str, svc: Services = Svc) -> RunReport:
    return _report(svc, run_id)


@router.get("/runs/{run_id}/report.csv", response_class=PlainTextResponse)
def run_report_csv(run_id: str, svc: Services = Svc) -> PlainTextResponse:
    return PlainTextResponse(
        report_csv(_report(svc, run_id)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_report.csv"'},
    )


@router.get("/runs/{run_id}/rejects/{table}")
def run_rejects(
    run_id: str,
    table: str,
    limit: int = Query(100, ge=0, le=10_000),
    offset: int = Query(0, ge=0),
    svc: Services = Svc,
) -> dict[str, Any]:
    plan = _plan(svc, _run(svc, run_id).plan_id)
    names = {t.name.lower(): t.name for t in plan.tables} | {
        t.target_table.lower(): t.name for t in plan.tables
    }
    name = names.get(table.lower())
    if name is None:
        raise _404("table", table)
    rows, total = read_rejects(table_paths(svc.data_dir, run_id, name).rejects, limit, offset)
    return {"rows": rows, "total": total}
