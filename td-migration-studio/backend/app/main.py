"""FastAPI entrypoint. Routers live in app/api/ (owned by the pipeline+API workstream)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import Services, router
from .pipeline.control import PgControlRepo
from .pipeline.orchestrator import Orchestrator
from .pipeline.planner import Planner
from .settings import get_settings

log = logging.getLogger(__name__)


def default_services() -> Services:
    s = get_settings()
    repo = PgControlRepo(s.ctl_dsn)
    repo.init_schema()
    planner = Planner()
    return Services(repo, planner, Orchestrator(repo, s.data_dir), s.data_dir)


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = services or default_services()
        interrupted = svc.repo.mark_interrupted()
        if interrupted:
            log.warning("marked %d interrupted run(s) resumable: %s", len(interrupted), interrupted)
        app.state.services = svc
        try:
            yield
        finally:
            if services is None and hasattr(svc.repo, "close"):
                svc.repo.close()

    app = FastAPI(title="TD Migration Studio API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(router)
    return app


app = create_app()
