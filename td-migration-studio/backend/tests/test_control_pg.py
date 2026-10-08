"""Control repository against the docker compose Postgres (ctl DB)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from app.contracts.models import (
    CheckResult,
    MigrationPlan,
    ObjectState,
    PlanRequest,
    Run,
    RunStatus,
    Stage,
    TableProfile,
    TargetSummary,
)
from app.pipeline.control import PgControlRepo
from app.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def repo():
    try:
        r = PgControlRepo(get_settings().ctl_dsn, timeout=3)
        r.init_schema()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ctl Postgres not reachable: {exc}")
    yield r
    with r.pool.connection() as conn:  # leave no test rows behind in the shared ctl DB
        for t in ("run_events", "run_checks", "run_objects", "runs"):
            conn.execute(f"DELETE FROM ctl.{t} WHERE run_id LIKE 'run_pgtest_%'")
        conn.execute("DELETE FROM ctl.plans WHERE plan_id LIKE 'plan_pgtest_%'")
        conn.execute("DELETE FROM ctl.object_registry WHERE target_table LIKE 'ds.run_pgtest_%'")
    r.close()


def test_control_repo_roundtrip(repo):
    now = datetime.now(timezone.utc)
    pid, rid = f"plan_pgtest_{uuid.uuid4().hex[:8]}", f"run_pgtest_{uuid.uuid4().hex[:8]}"
    plan = MigrationPlan(
        id=pid,
        created_at=now,
        request=PlanRequest(tables=["A"], target_id="bigquery"),
        target=TargetSummary(
            id="bigquery", display_name="BQ", vendor="g", modes=["simulated"], real_ready=False
        ),
        tables=[],
    )
    repo.save_plan(plan)
    repo.save_plan(plan.model_copy(update={"status": "approved"}))
    assert repo.get_plan(pid).status == "approved"

    repo.create_run(
        Run(
            id=rid,
            plan_id=pid,
            target_id="bigquery",
            target_mode="simulated",
            status=RunStatus.RUNNING,
            created_at=now,
            objects=[
                ObjectState(table="A", target_table="ds.a"),
                ObjectState(table="B", target_table="ds.b"),
            ],
        )
    )
    repo.update_object(
        rid,
        "A",
        stage=Stage.STAGED,
        rows_extracted=10,
        staged_path="/x",
        source_profile=TableProfile(row_count=10),
    )
    rec = repo.get_object(rid, "A")
    assert rec.stage == Stage.STAGED and rec.source_profile.row_count == 10 and rec.staged_path == "/x"

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: repo.add_event(rid, "log", f"m{i}", table="A", data={"i": i}), range(40)))
    events = repo.list_events(rid)
    assert [e.seq for e in events] == list(range(1, 41))
    assert [e.seq for e in repo.list_events(rid, after=35)] == [36, 37, 38, 39, 40]

    checks = [CheckResult(name="row_count", passed=True), CheckResult(name="sum", column="x", passed=False)]
    repo.save_checks(rid, "A", checks)
    repo.save_checks(rid, "A", checks)  # idempotent
    assert len(repo.list_checks(rid)["A"]) == 2

    repo.upsert_registry(
        {
            "target_id": "bigquery",
            "target_mode": "simulated",
            "target_table": f"ds.{rid}",
            "source_table": "DB.A",
            "definition_hash": "h",
            "last_run_id": rid,
            "last_load_id": "l1",
            "row_count": 10,
            "checksum": "1",
        }
    )
    repo.upsert_registry(
        {
            "target_id": "bigquery",
            "target_mode": "simulated",
            "target_table": f"ds.{rid}",
            "source_table": "DB.A",
            "definition_hash": "h",
            "last_run_id": rid,
            "last_load_id": "l2",
            "row_count": 10,
            "checksum": "1",
        }
    )
    reg = [r for r in repo.list_registry() if r["target_table"] == f"ds.{rid}"]
    assert len(reg) == 1 and reg[0]["last_load_id"] == "l2"

    assert rid in repo.mark_interrupted()
    run = repo.get_run(rid)
    assert run.status == RunStatus.FAILED
    assert {o.table: o.stage for o in run.objects} == {"A": Stage.FAILED, "B": Stage.PENDING}
    assert any("interrupted" in e.message for e in repo.list_events(rid))
