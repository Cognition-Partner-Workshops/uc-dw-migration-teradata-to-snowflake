"""Job orchestration: persist uploads, run analyse -> convert -> data validation, simulated load, outputs."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .config_analyser import analyse_config
from .conversion import convert_all
from .data_analyser import TablePlan, analyse_data
from .ingest import UploadedFile, expand
from .loader import run_load
from .models import Analysis, Conversion, InputFile, Job, JobOptions, Progress, Stage, TargetId
from .outputs import TARGET_LABEL, output_files

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
        p = self.dir(job.id) / "job.json"
        tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(job.model_dump_json(indent=1))
        os.replace(tmp, p)

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

    def recover_interrupted(self) -> None:
        for job in self.list():
            if job.status == "running":
                job.status, job.error = "failed", "Interrupted: the server restarted while this job was running"
                self.save(job)

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upload_summary(files: list[tuple[str, bytes]], kind: str) -> list[InputFile]:
    out = []
    for name, data in files:
        n = PurePosixPath(name).name.lower()
        fmt = "zip" if n.endswith(".zip") else (PurePosixPath(n.removesuffix(".gz")).suffix.lstrip(".") or "file")
        out.append(InputFile(path=PurePosixPath(name).name, size=len(data), kind=kind, detected_format=fmt))
    return out


def _conversion_summary(conversions: list[Conversion]) -> str:
    n = {s: sum(c.status == s for c in conversions) for s in ("converted", "converted_with_warnings", "manual_review", "unsupported")}
    msg = (
        f"{len(conversions)} object(s) processed: {n['converted'] + n['converted_with_warnings']} converted automatically, "
        f"{n['manual_review']} draft(s) need manual review"
    )
    return msg + (f", {n['unsupported']} unsupported" if n["unsupported"] else "")


STAGES = [
    ("upload", "Upload received and unpacked", 5),
    ("config", "Configuration analysis: objects and dependencies", 20),
    ("convert", "Conversion: Teradata SQL to {target}", 35),
    ("data", "Data analysis: formats, columns and table mappings", 30),
    ("outputs", "Migration outputs: SQL, reports and load scripts", 10),
]


class Tracker:
    """Records stage-by-stage progress on the job and persists it (throttled) so the UI can poll it."""

    def __init__(self, store: JobStore, job: Job, pace: float = 0.0) -> None:
        self.store, self.job, self.pace = store, job, pace
        self._saved = 0.0
        self._stage_t0 = 0.0
        target = TARGET_LABEL.get(job.options.targets[0], job.options.targets[0]) if job.options.targets else "target"
        job.progress = Progress(started_at=_now(), stages=[Stage(key=k, label=lbl.format(target=target), weight=w) for k, lbl, w in STAGES])

    @property
    def p(self) -> Progress:
        assert self.job.progress is not None
        return self.job.progress

    def _stage(self, key: str) -> Stage:
        return next(s for s in self.p.stages if s.key == key)

    def _recompute(self) -> None:
        total = sum(s.weight for s in self.p.stages)
        self.p.percent = min(100, round(sum(s.weight * s.percent for s in self.p.stages) / total))

    def _save(self, force: bool = False) -> None:
        if force or time.monotonic() - self._saved > 0.25:
            self._saved = time.monotonic()
            self.store.save(self.job)

    def start(self, key: str, detail: str | None = None) -> None:
        st = self._stage(key)
        st.status, st.started_at, st.detail, st.percent = "running", _now(), detail, 0
        self.p.current = key
        self._stage_t0 = time.monotonic()
        self._save(force=True)

    def step(self, key: str, done: int, total: int, detail: str | None = None) -> None:
        st = self._stage(key)
        st.percent = min(99, round(100 * done / total)) if total else 0
        if detail:
            st.detail = detail
        self._recompute()
        if self.pace and total:
            time.sleep(self.pace / total)
        self._save()

    def _pad(self, key: str) -> None:
        """Presentation pace: stretch short stages to `pace` seconds so each one is visible in a live demo."""
        remaining = self.pace - (time.monotonic() - self._stage_t0)
        st = self._stage(key)
        ticks = 8
        for i in range(ticks):
            if remaining <= 0:
                break
            time.sleep(remaining / ticks)
            st.percent = max(st.percent, round(100 * (i + 1) / (ticks + 1)))
            self._recompute()
            self._save()

    def finish(self, key: str, detail: str | None = None) -> None:
        if self.pace:
            self._pad(key)
        st = self._stage(key)
        st.status, st.finished_at, st.percent = "done", _now(), 100
        if detail:
            st.detail = detail
        self._recompute()
        self._save(force=True)

    def fail(self) -> None:
        for st in self.p.stages:
            if st.status == "running":
                st.status, st.finished_at = "failed", _now()
        self.p.finished_at, self.p.current = _now(), None
        self._save(force=True)

    def complete(self) -> None:
        self.p.finished_at, self.p.current, self.p.percent = _now(), None, 100


def create_job(
    store: JobStore,
    name: str,
    config: list[tuple[str, bytes]],
    data: list[tuple[str, bytes]],
    options: JobOptions,
    background: bool = False,
    pace: float = 0.0,
) -> Job:
    config_files, data_files = expand(config), expand(data)
    job = Job(
        id=uuid.uuid4().hex[:12],
        name=name or "Migration job",
        created_at=_now(),
        status="running",
        options=options,
        uploads=_upload_summary(config, "config") + _upload_summary(data, "data"),
    )
    store.dir(job.id).mkdir(parents=True)
    tracker = Tracker(store, job, pace)
    tracker.start("upload")
    store.write_files(job.id, "config", config_files)
    store.write_files(job.id, "data", data_files)
    n_in = len(config) + len(data)
    tracker.finish("upload", f"{n_in} upload(s) unpacked into {len(config_files)} configuration and {len(data_files)} data file(s)")
    if background:
        threading.Thread(target=analyse, args=(store, job, tracker), daemon=True).start()
        return job
    return analyse(store, job, tracker)


def _data_step(store: JobStore, job: Job, a: Analysis) -> dict[str, TablePlan]:
    tables = {o.id: o.table for o in a.objects if o.table}
    inputs, files, plans, manifest, msgs = analyse_data(
        store.read_files(job.id, "data"), tables, job.options.data, job.extra.get("overrides", {})
    )
    a.data_files, a.data, a.manifest = inputs, files, manifest
    a.readiness = [p.readiness for p in plans.values()]
    a.messages = [m for m in a.messages if not m.startswith("[data] ")] + [f"[data] {m}" for m in msgs]
    return plans


def analyse(store: JobStore, job: Job, tracker: Tracker | None = None) -> Job:
    tr = tracker or Tracker(store, job)
    try:
        o = job.options
        tr.start("config")
        inputs, objects, order, msgs = analyse_config(store.read_files(job.id, "config"), o.config_format)
        a = Analysis(config_files=inputs, objects=objects, create_order=order, messages=msgs)
        job.analysis = a
        tr.finish("config", f"{len(objects)} object(s) found in {len(inputs)} file(s); create order resolved")

        tr.start("convert")
        a.conversions, a.type_mappings = convert_all(
            objects,
            order,
            o.targets,
            o.schema_map,
            o.gcp_project,
            lambda d, n, obj: tr.step("convert", d, n, f"Converting {obj} ({d + 1}/{n})"),
        )
        tr.finish("convert", _conversion_summary(a.conversions))

        tr.start("data")
        _data_step(store, job, a)
        rows = sum(r.total_rows for r in a.readiness)
        tr.finish("data", f"{len(a.data)} data file(s), {rows:,} row(s) checked against {len(a.readiness)} table(s)")

        tr.start("outputs")
        files = output_files(a, o)
        tr.finish("outputs", f"{len(files)} output file(s) ready")
        tr.complete()
        job.status, job.error, job.loads = "analysed", None, {}
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        job.status, job.error = "failed", f"Analysis failed: {exc}"
        tr.fail()
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
