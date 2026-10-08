"""FastAPI entry point: `uvicorn app.main:app --reload` from backend/."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config, db, service
from .scanner import RepoError


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Teradata -> Azure Synapse migration tool", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


class CreateJobRequest(BaseModel):
    repo_url: str = Field(
        ..., examples=["https://github.com/Cognition-Partner-Workshops/uc-dw-migration-teradata-to-snowflake"]
    )


class ConvertRequest(BaseModel):
    object_ids: list[int] | None = Field(None, description="Subset of object IDs to convert; omit to convert all.")


def _job_or_404(fn, *args):
    try:
        return fn(*args)
    except service.JobNotFound:
        raise HTTPException(404, "Job not found") from None
    except service.JobStateError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=201)
def create_job(req: CreateJobRequest) -> dict:
    try:
        return service.create_job(req.repo_url)
    except RepoError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_or_404(service.get_job, job_id)


@app.post("/jobs/{job_id}/convert")
def convert_job(job_id: str, req: ConvertRequest | None = None) -> dict:
    return _job_or_404(service.convert_job, job_id, req.object_ids if req else None)


@app.get("/jobs/{job_id}/objects/{object_id}")
def get_object(job_id: str, object_id: int) -> dict:
    detail = _job_or_404(service.get_object_detail, job_id, object_id)
    if detail is None:
        raise HTTPException(404, "Object not found")
    return detail


@app.get("/jobs/{job_id}/report", response_class=PlainTextResponse)
def get_report(job_id: str) -> str:
    _job_or_404(service.get_job, job_id)
    path = service.job_output_dir(job_id) / service.REPORT_NAME
    if not path.is_file():
        raise HTTPException(409, "Job has not been converted yet")
    return path.read_text(encoding="utf-8")


@app.get("/output/{job_id}/{file_path:path}")
def serve_output(job_id: str, file_path: str) -> FileResponse:
    """Serve generated artifacts from output/{job_id}/."""
    root = service.job_output_dir(job_id).resolve()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "File not found")
    media = "text/markdown" if target.suffix == ".md" else "text/plain"
    return FileResponse(target, media_type=f"{media}; charset=utf-8")


@app.get("/jobs/{job_id}/download")
def download(job_id: str) -> StreamingResponse:
    buf = _job_or_404(service.build_zip, job_id)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="synapse_migration_{job_id}.zip"'},
    )
