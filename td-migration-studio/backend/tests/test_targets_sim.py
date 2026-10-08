from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import duckdb
import pytest
from target_fixtures import MIXED, ORDER_REVIEWS, ORDERS, mixed_rows, plan, write_parquet

from app.connectors.registry import get_target_connector, get_target_meta
from app.contracts.checksum import duckdb_checksum_sql
from app.contracts.models import MigrationPlan, PlanRequest, ProfileSpec, TargetSummary

TARGETS = ["synapse", "bigquery", "redshift"]
SPEC = ProfileSpec(
    numeric_columns=["amount", "score", "lat"],
    null_columns=["name", "ts_tz"],
    checksum_columns=[c.name for c in MIXED.columns],
    unique_keys=[["id"]],
)


@pytest.fixture(params=TARGETS)
def target(request, tmp_path):
    tid = request.param
    conn = get_target_connector(tid, "simulated", {"duckdb_path": str(tmp_path / f"{tid}.duckdb")}, {})
    yield tid, conn
    conn.close()


def reference(path, schema):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW v AS SELECT * FROM read_parquet('{path}')")
    return con.execute(duckdb_checksum_sql("v", schema)).fetchone()


def test_registered_modes():
    for tid in TARGETS:
        assert get_target_connector(tid, "simulated", {}, {}).__class__.__name__.startswith("Simulated")
        assert get_target_connector(tid, "real", {}, {}).__class__.__name__.startswith("Real")


def test_load_reload_profile_checksum(target, tmp_path):
    tid, conn = target
    tp = plan(tid, MIXED)
    f1 = tmp_path / "a.parquet"
    schema = write_parquet(f1, tid, tp, mixed_rows(120))
    assert conn.test_connection().ok
    conn.ensure_container(tp.target_container)
    conn.create_table(tp)
    r1 = conn.load(tp, [f1], "run1")
    assert r1.rows_loaded == 120 and 'CREATE TABLE "retail_dw"."mixed"' in r1.details["duckdb_ddl"]
    assert r1.details["native_ddl"] == conn.render_ddl(tp)
    r2 = conn.load(tp, [f1], "run1")  # same load id re-run: still no duplicates
    assert r2.rows_loaded == 120
    prof = conn.profile(tp, SPEC)
    rows, checksum = reference(f1, schema)
    assert prof.row_count == rows == 120 and prof.checksum == checksum
    assert prof.duplicate_key_count == {"id": 0}
    cols = {c.column: c for c in prof.columns}
    assert cols["name"].null_count == cols["ts_tz"].null_count == 17
    assert float(cols["amount"].sum) == float(sum(v for v in mixed_rows(120)["amount"] if v is not None))
    assert int(cols["score"].min) == -128

    # replace semantics: a reload with different data fully replaces the table
    f2 = tmp_path / "b.parquet"
    write_parquet(f2, tid, tp, mixed_rows(30, offset=500))
    f3 = tmp_path / "c.parquet"
    write_parquet(f3, tid, tp, mixed_rows(10, offset=500))  # duplicates of f2's first ids
    r3 = conn.load(tp, [f2, f3], "run2")
    assert r3.rows_loaded == 40
    assert conn.profile(tp, SPEC).duplicate_key_count == {"id": 10}
    conn.create_table(tp)  # unchanged DDL: keeps data
    assert conn.profile(tp, ProfileSpec()).row_count == 40
    leftover = conn._query("SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE '%__stg_%'")[0][0]
    assert leftover == 0
    conn.drop_table(tp)
    assert not conn._query("SELECT * FROM duckdb_tables() WHERE table_name = 'mixed'")


def test_failed_load_keeps_previous_data(target, tmp_path):
    tid, conn = target
    tp = plan(tid, MIXED)
    good = tmp_path / "good.parquet"
    write_parquet(good, tid, tp, mixed_rows(5))
    conn.create_table(tp)
    conn.load(tp, [good], "ok")
    bad = tp.model_copy(deep=True)
    bad.columns[0].target_name = "missing_col"
    bad.columns[0].source = bad.columns[0].source.model_copy(update={"name": "missing_col"})
    with pytest.raises(ValueError, match="not found in staged Parquet"):
        conn.load(bad.model_copy(update={"target_table": "mixed"}), [good], "bad")
    assert conn.profile(tp, ProfileSpec()).row_count == 5


def test_concurrent_loads(target, tmp_path):
    tid, conn = target
    plans = [plan(tid, MIXED).model_copy(update={"target_table": f"mixed_{i}"}) for i in range(4)]
    files = []
    for i, tp in enumerate(plans):
        files.append(tmp_path / f"{i}.parquet")
        write_parquet(files[-1], tid, tp, mixed_rows(50 + i))
        conn.create_table(tp)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda a: conn.load(a[0], [a[1]], "l"), zip(plans, files, strict=True)))
    assert [r.rows_loaded for r in results] == [50, 51, 52, 53]


def test_access_script(target):
    tid, conn = target
    meta = get_target_meta(tid)
    tables = [plan(tid, ORDERS), plan(tid, ORDER_REVIEWS, pii={"review_comment_message": "nullify"})]
    mp = MigrationPlan(
        id="p",
        created_at=datetime.now(),
        request=PlanRequest(tables=[], target_id=tid),
        target=TargetSummary(
            id=tid, display_name=meta.display_name, vendor=meta.vendor, modes=["simulated"], real_ready=False
        ),
        tables=tables,
    )
    script = conn.access_script(mp)
    assert "{" not in script.replace("{{", "")  # all placeholders rendered
    assert "review_comment_message" in script and "orders" in script
    assert "GRANT" in script
