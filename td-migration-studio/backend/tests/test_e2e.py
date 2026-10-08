"""Planner -> run -> report with fakes, incl. injected failure + resume (no re-extract, no duplicates)."""

from __future__ import annotations

import pyarrow.parquet as pq

from app.contracts.models import (
    ColumnOverride,
    FailureInjection,
    PlanRequest,
    RunOptions,
    RunStatus,
    Stage,
)
from app.pipeline.report import report_csv


def _plan(planner, repo, **opts):
    plan = planner.create(PlanRequest(tables=[], target_id="bigquery", options=RunOptions(**opts)))
    plan = planner.approve(plan)
    repo.save_plan(plan)
    return plan


def _target_rows(tmp_path, tp):
    files = sorted((tmp_path / "wh" / "bigquery" / tp.target_container / tp.target_table).glob("*.parquet"))
    return sum(pq.ParquetFile(f).metadata.num_rows for f in files)


def test_plan_contents(env, source):
    repo, planner, _ = env
    plan = planner.create(PlanRequest(tables=[], target_id="bigquery"))
    assert plan.summary["tables"] == 6
    orders = next(t for t in plan.tables if t.name == "ORDERS")
    assert orders.target_options["partition_column"] == "order_purchase_timestamp"
    assert orders.ddl.startswith("CREATE TABLE")
    assert plan.access_script and plan.governance_notes
    pii = {(t.name, c.source.name): c.pii for t in plan.tables for c in t.columns if c.pii}
    assert pii[("CUSTOMERS", "customer_unique_id")].category == "identifier"
    assert any(w.severity == "info" and w.column == "product_weight_g" for w in plan.warnings)
    # overrides re-render DDL
    plan2 = planner.apply_overrides(
        plan, [ColumnOverride(table="ORDERS", column="order_status", target_type="STRING")]
    )
    o2 = next(t for t in plan2.tables if t.name == "ORDERS")
    assert "order_status STRING\n" in o2.ddl or "order_status STRING," in o2.ddl


def test_run_failure_resume_and_retry(env, source, target_log, tmp_path):
    repo, planner, orch = env
    plan = _plan(
        planner,
        repo,
        parallelism=3,
        max_attempts=2,
        batch_rows=64,
        inject_failures=[FailureInjection(table="ORDERS", stage="loading", times=2)],
    )
    source.extract_calls.clear()  # planner sampling is not a full extract
    run = orch.start(plan)
    orch.wait(run.id, 60)
    run = repo.get_run(run.id)
    assert run.status == RunStatus.PARTIAL
    states = {o.table: o for o in run.objects}
    assert states["ORDERS"].stage == Stage.FAILED and "injected" in states["ORDERS"].error
    assert all(o.stage == Stage.PASSED for n, o in states.items() if n != "ORDERS")
    assert all(n == 1 for n in source.extract_calls.values()) and len(source.extract_calls) == 6

    report = repo.get_report(run.id)
    assert report.totals.failed == 1 and report.totals.passed == 5

    loads_before = dict(target_log["loads"])
    run = orch.resume(run.id)
    orch.wait(run.id, 60)
    run = repo.get_run(run.id)
    assert run.status == RunStatus.SUCCEEDED, [(o.table, o.error) for o in run.objects]
    # passed tables untouched; ORDERS resumed from staged Parquet (no re-extract)
    assert all(n == 1 for n in source.extract_calls.values())
    assert {k: v for k, v in target_log["loads"].items() if k != "ORDERS"} == {
        k: v for k, v in loads_before.items() if k != "ORDERS"
    }
    orders_tp = next(t for t in plan.tables if t.name == "ORDERS")
    assert _target_rows(tmp_path, orders_tp) == 200  # loaded 3x overall, REPLACE => no duplicates

    report = repo.get_report(run.id)
    assert report.totals.passed == 6 and report.totals.rows_loaded == report.totals.rows_source
    by = {t.table: t for t in report.tables}
    assert all(t.checksum_match for t in report.tables)
    ri = [c for c in by["PRODUCTS"].checks if c.name == "referential_integrity"]
    assert ri and ri[0].target_value == "1" and ri[0].passed and "pc_gamer" in ri[0].detail
    uniq = [c for c in by["ORDER_REVIEWS"].checks if c.name == "uniqueness"]
    assert uniq[0].column == "review_id,order_id" and uniq[0].passed
    assert report.governance["masked_columns"] > 0
    csv = report_csv(report)
    assert csv.count("\n") == 7 and "ORDERS" in csv

    # explicit retry re-runs from staged data, still no duplicates and no re-extract
    orch.retry(run.id, ["orders"])
    orch.wait(run.id, 60)
    assert repo.get_run(run.id).status == RunStatus.SUCCEEDED
    assert _target_rows(tmp_path, orders_tp) == 200 and source.extract_calls["ORDERS"] == 1

    seqs = [e.seq for e in repo.list_events(run.id, 0, 100_000)]
    assert seqs == list(range(1, len(seqs) + 1))
    assert any(e.kind == "state" and e.data.get("stage") == "passed" for e in repo.list_events(run.id))


def test_masked_values_reach_target(env, tmp_path):
    repo, planner, orch = env
    plan = _plan(planner, repo)
    run = orch.start(plan)
    orch.wait(run.id, 60)
    tp = next(t for t in plan.tables if t.name == "CUSTOMERS")
    d = tmp_path / "wh" / "bigquery" / tp.target_container / tp.target_table
    vals = pq.read_table(sorted(d.glob("*.parquet"))).column("contact_info").to_pylist()
    assert all("@" not in v for v in vals)


def test_dq_failure_fails_table(env, target_log):
    repo, planner, orch = env
    target_log["corrupt"] = "PRODUCTS"
    plan = _plan(planner, repo, max_attempts=1)
    run = orch.start(plan)
    orch.wait(run.id, 60)
    run = repo.get_run(run.id)
    products = next(o for o in run.objects if o.table == "PRODUCTS")
    assert run.status == RunStatus.PARTIAL and products.stage == Stage.FAILED
    assert "row_count" in products.error


def test_mark_interrupted_makes_runs_resumable(env, source):
    repo, planner, orch = env
    plan = _plan(planner, repo)
    from app.contracts.models import Run
    from app.pipeline.control import utcnow

    repo.create_run(
        Run(
            id="run_x",
            plan_id=plan.id,
            target_id="bigquery",
            target_mode="simulated",
            status=RunStatus.RUNNING,
            created_at=utcnow(),
            objects=[
                __import__("app.contracts.models", fromlist=["ObjectState"]).ObjectState(
                    table=t.name, target_table=t.target_table
                )
                for t in plan.tables
            ],
        )
    )
    assert repo.mark_interrupted() == ["run_x"]
    assert repo.get_run("run_x").status == RunStatus.FAILED
    orch.resume("run_x")
    orch.wait("run_x", 60)
    assert repo.get_run("run_x").status == RunStatus.SUCCEEDED
