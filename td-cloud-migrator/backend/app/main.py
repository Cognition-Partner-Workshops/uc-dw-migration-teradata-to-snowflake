"""FastAPI app: upload dumps, analyse/convert, review mappings, simulated load and output downloads."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import pipeline
from .ingest import (
    CONFIG_EXTENSIONS,
    CONFIG_FORMATS,
    DATA_EXTENSIONS,
    DATA_FORMATS,
    DELIMITERS,
)
from .models import TARGETS, Job, JobOptions, TargetId
from .outputs import TARGET_LABEL, bundle

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
FRONTEND_DIST = ROOT / "frontend" / "dist"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

app = FastAPI(title="Teradata to Cloud Migrator", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"]
)
store = pipeline.JobStore()
store.recover_interrupted()
HISTORY_LIMIT = 10
MAX_PACE_SECONDS = 3.0


def _job(job_id: str) -> Job:
    try:
        return store.get(job_id)
    except KeyError:
        raise HTTPException(404, "job not found") from None


def _ready(job: Job) -> Job:
    if job.status == "running":
        raise HTTPException(409, "job is still running")
    if job.analysis is None:
        raise HTTPException(409, "job not analysed")
    return job


def _one_target(opts: JobOptions) -> None:
    if len(opts.targets) != 1:
        raise HTTPException(422, "choose exactly one target: bigquery, redshift or synapse")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/formats")
def formats() -> dict:
    return {
        "config": {"formats": CONFIG_FORMATS, "extensions": CONFIG_EXTENSIONS},
        "data": {"formats": DATA_FORMATS, "extensions": DATA_EXTENSIONS, "delimiters": DELIMITERS},
        "targets": {t: TARGET_LABEL[t] for t in TARGETS},
    }


async def _read(files: list[UploadFile] | None) -> list[tuple[str, bytes]]:
    out, total = [], 0
    for f in files or []:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "upload too large")
        if f.filename:
            out.append((f.filename, data))
    return out


@app.post("/api/jobs")
async def create_job(
    config_files: Annotated[list[UploadFile] | None, File()] = None,
    data_files: Annotated[list[UploadFile] | None, File()] = None,
    options: Annotated[str, Form()] = "{}",
    name: Annotated[str, Form()] = "",
) -> Job:
    try:
        opts = JobOptions.model_validate(json.loads(options or "{}"))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, f"invalid options: {exc}") from None
    _one_target(opts)
    config, data = await _read(config_files), await _read(data_files)
    if not config:
        raise HTTPException(422, "at least one configuration file is required")
    try:
        return pipeline.create_job(store, name, config, data, opts, background=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _summary(j: Job) -> dict:
    a, p = j.analysis, j.progress
    duration = None
    if p and p.finished_at:
        duration = round((datetime.fromisoformat(p.finished_at) - datetime.fromisoformat(p.started_at)).total_seconds(), 1)
    return {
        "id": j.id,
        "name": j.name,
        "created_at": j.created_at,
        "status": j.status,
        "targets": j.options.targets,
        "uploads": [u.path for u in j.uploads],
        "objects": len(a.objects) if a else 0,
        "data_files": len(a.data) if a else 0,
        "rows": sum(r.total_rows for r in a.readiness) if a else 0,
        "manual_review": sum(c.status in ("manual_review", "unsupported") for c in a.conversions) if a else 0,
        "loaded_rows": sum(t.loaded_rows for r in j.loads.values() for t in r.tables),
        "duration_seconds": duration,
        "error": j.error,
    }


@app.get("/api/jobs")
def list_jobs(limit: int = HISTORY_LIMIT) -> dict:
    jobs = store.list()
    limit = max(1, min(limit, HISTORY_LIMIT))
    return {"jobs": [_summary(j) for j in jobs[:limit]], "total": len(jobs), "limit": limit}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    return _job(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    _job(job_id)
    store.delete(job_id)
    return {"deleted": job_id}


class MappingUpdate(BaseModel):
    overrides: dict[str, str]


@app.post("/api/jobs/{job_id}/mappings")
def update_mappings(job_id: str, body: MappingUpdate) -> Job:
    job = _ready(_job(job_id))
    assert job.analysis is not None
    valid = {o.id for o in job.analysis.objects if o.table} | {""}
    bad = [v for v in body.overrides.values() if v not in valid]
    if bad:
        raise HTTPException(422, f"unknown table(s): {bad}")
    return pipeline.set_overrides(store, job, body.overrides)


class LoadRequest(BaseModel):
    targets: list[TargetId] | None = None


@app.post("/api/jobs/{job_id}/load")
def load(job_id: str, body: LoadRequest) -> Job:
    job = _ready(_job(job_id))
    return pipeline.load(store, job, body.targets or job.options.targets)


@app.get("/api/jobs/{job_id}/outputs")
def outputs(job_id: str) -> dict[str, str]:
    return pipeline.outputs(_job(job_id))


@app.get("/api/jobs/{job_id}/outputs/{path:path}")
def output_file(job_id: str, path: str) -> PlainTextResponse:
    files = pipeline.outputs(_job(job_id))
    if path not in files:
        raise HTTPException(404, "no such output")
    return PlainTextResponse(files[path])


@app.get("/api/jobs/{job_id}/bundle.zip")
def download_bundle(job_id: str) -> Response:
    job = _job(job_id)
    return Response(
        bundle(pipeline.outputs(job)),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="migration_output_{job.id}.zip"'},
    )


def _example_files(name: str) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    base = EXAMPLES / name
    if not base.is_dir() or not name.replace("_", "").isalnum():
        raise HTTPException(404, "unknown example")
    cfg = base / "config_dump.zip"
    data = base / "data_dump.zip"
    return [(cfg.name, cfg.read_bytes())], [(data.name, data.read_bytes())]


@app.get("/api/examples")
def examples() -> list[dict]:
    return (
        [
            {
                "name": p.name,
                "files": sorted(f.name for f in p.iterdir() if f.suffix == ".zip"),
                "readme": (p / "README.md").read_text() if (p / "README.md").exists() else "",
            }
            for p in sorted(EXAMPLES.iterdir())
            if p.is_dir()
        ]
        if EXAMPLES.exists()
        else []
    )


@app.get("/api/examples/{name}/{file}")
def example_file(name: str, file: str) -> FileResponse:
    p = (EXAMPLES / name / file).resolve()
    if EXAMPLES.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p, filename=p.name)


@app.post("/api/examples/{name}/run")
def run_example(name: str, target: TargetId = "bigquery", pace: float = 0.0) -> Job:
    config, data = _example_files(name)
    opts = JobOptions(targets=[target])
    return pipeline.create_job(store, f"Example: {name}", config, data, opts, background=True, pace=max(0.0, min(pace, MAX_PACE_SECONDS)))


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
