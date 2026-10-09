"""Job orchestration: persist uploads, run analyse -> convert -> data validation, simulated load, outputs."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config_analyser import analyse_config
from .conversion import convert_all
from .data_analyser import TablePlan, analyse_data
from .ingest import UploadedFile, expand
from .loader import run_load
from .models import Analysis, Job, JobOptions, TargetId
from .outputs import output_files

DATA_DIR = Path(os.environ.get("TDCM_DATA_DIR", Path(__file__).resolve().parents[1] / "var"))


class JobStore:
    def __init__(self, root: Path = DATA_DIR) -> None:
        self.root = root / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)

    def dir(self, job_id: str) -> Path:
        if not job_id.isalnum():
            raise KeyError(job_id)
        return self.root / job_id

    def save(self, job: Job) -> None:
        (self.dir(job.id) / "job.json").write_text(job.model_dump_json(indent=1))

    def get(self, job_id: str) -> Job:
        p = self.dir(job_id) / "job.json"
        if not p.exists():
            raise KeyError(job_id)
        return Job.model_validate_json(p.read_text())

    def list(self) -> list[Job]:
        jobs = []
        for p in self.root.glob("*/job.json"):
            try:
                jobs.append(Job.model_validate_json(p.read_text()))
            except ValueError:
                continue
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.dir(job_id), ignore_errors=True)

    def write_files(self, job_id: str, kind: str, files: list[UploadedFile]) -> None:
        base = self.dir(job_id) / kind
        for f in files:
            p = (base / f.path).resolve()
            if base.resolve() not in p.parents:
                raise ValueError(f"unsafe path {f.path}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f.data)

    def read_files(self, job_id: str, kind: str) -> list[UploadedFile]:
        base = self.dir(job_id) / kind
        return [UploadedFile(p.relative_to(base).as_posix(), p.read_bytes()) for p in sorted(base.rglob("*")) if p.is_file()]


def create_job(store: JobStore, name: str, config: list[tuple[str, bytes]], data: list[tuple[str, bytes]], options: JobOptions) -> Job:
    config_files, data_files = expand(config), expand(data)
    job = Job(
        id=uuid.uuid4().hex[:12],
        name=name or "Migration job",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="uploaded",
        options=options,
    )
    store.dir(job.id).mkdir(parents=True)
    store.write_files(job.id, "config", config_files)
    store.write_files(job.id, "data", data_files)
    store.save(job)
    return analyse(store, job)


def _data_step(store: JobStore, job: Job, a: Analysis) -> dict[str, TablePlan]:
    tables = {o.id: o.table for o in a.objects if o.table}
    inputs, files, plans, manifest, msgs = analyse_data(
        store.read_files(job.id, "data"), tables, job.options.data, job.extra.get("overrides", {})
    )
    a.data_files, a.data, a.manifest = inputs, files, manifest
    a.readiness = [p.readiness for p in plans.values()]
    a.messages = [m for m in a.messages if not m.startswith("[data] ")] + [f"[data] {m}" for m in msgs]
    return plans


def analyse(store: JobStore, job: Job) -> Job:
    try:
        o = job.options
        inputs, objects, order, msgs = analyse_config(store.read_files(job.id, "config"), o.config_format)
        conversions, mappings = convert_all(objects, order, o.targets, o.schema_map, o.gcp_project)
        a = Analysis(
            config_files=inputs, objects=objects, create_order=order, conversions=conversions, type_mappings=mappings, messages=msgs
        )
        _data_step(store, job, a)
        job.analysis, job.status, job.error, job.loads = a, "analysed", None, {}
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        job.status, job.error = "failed", f"Analysis failed: {exc}"
    store.save(job)
    return job


def set_overrides(store: JobStore, job: Job, overrides: dict[str, str]) -> Job:
    job.extra["overrides"] = {**job.extra.get("overrides", {}), **overrides}
    assert job.analysis is not None
    _data_step(store, job, job.analysis)
    job.loads = {}
    job.status = "analysed"
    store.save(job)
    return job


def load(store: JobStore, job: Job, targets: list[TargetId]) -> Job:
    a = job.analysis
    if a is None:
        raise ValueError("job has not been analysed")
    plans = _data_step(store, job, a)
    for t in targets:
        job.loads[t] = run_load(
            t, store.dir(job.id) / f"sim_{t}.duckdb", a.objects, a.create_order, plans, a.conversions, job.options.schema_map
        )
    job.status = "loaded"
    store.save(job)
    return job


def outputs(job: Job) -> dict[str, str]:
    if job.analysis is None:
        return {}
    files = output_files(job.analysis, job.options)
    if job.loads:
        files["load_validation.json"] = json.dumps({t: r.model_dump() for t, r in job.loads.items()}, indent=1)
    return files
