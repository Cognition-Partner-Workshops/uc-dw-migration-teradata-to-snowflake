"""Process-wide services (control store, planner, orchestrator) shared by the routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from ..pipeline.control import ControlStore
from ..pipeline.orchestrator import Orchestrator
from ..pipeline.planner import Planner


@dataclass
class Services:
    repo: ControlStore
    planner: Planner
    orchestrator: Orchestrator
    data_dir: Path


def get_services(request: Request) -> Services:
    return request.app.state.services
