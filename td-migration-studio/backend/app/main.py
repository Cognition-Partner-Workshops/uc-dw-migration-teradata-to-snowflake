"""FastAPI entrypoint. Routers live in app/api/ (owned by the pipeline+API workstream)."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="TD Migration Studio API", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
