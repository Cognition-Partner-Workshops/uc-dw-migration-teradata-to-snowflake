from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import typemap
from app.connectors import registry
from app.pipeline.control import MemoryControlRepo
from app.pipeline.orchestrator import Orchestrator
from app.pipeline.planner import Planner

from .fakes import FakeSource, FakeTarget, fake_resolve_type, fake_target_type_info, olist_like


@pytest.fixture(autouse=True)
def fake_typemap(monkeypatch):
    monkeypatch.setattr(typemap, "resolve_type", fake_resolve_type)
    monkeypatch.setattr(typemap, "target_type_info", fake_target_type_info)


@pytest.fixture
def source() -> FakeSource:
    return FakeSource(olist_like())


@pytest.fixture
def target_log() -> dict[str, Any]:
    return {}


@pytest.fixture
def env(tmp_path: Path, source: FakeSource, target_log: dict[str, Any]):
    def target_factory(target_id, mode, connection, config):
        return FakeTarget(registry.get_target_meta(target_id), tmp_path / "wh" / target_id, target_log)

    repo = MemoryControlRepo()
    planner = Planner(source_factory=lambda: source, target_factory=target_factory)
    orch = Orchestrator(repo, tmp_path / "data", lambda: source, target_factory, backoff_s=0.0)
    return repo, planner, orch
