import duckdb
import pyarrow as pa

from app.connectors.registry import list_target_meta
from app.contracts.checksum import duckdb_checksum_sql
from app.contracts.models import PlanRequest

FROZEN_CONFIG_KEYS = {
    "bigquery": {
        "dataset",
        "location",
        "load_method",
        "partition_column",
        "partition_granularity",
        "clustering_columns",
        "require_partition_filter",
    },
    "synapse": {
        "schema",
        "dwu",
        "resource_class",
        "load_method",
        "distribution",
        "distribution_column",
        "index_type",
        "partition_column",
    },
    "redshift": {
        "schema",
        "node_type",
        "node_count",
        "load_method",
        "diststyle",
        "distkey",
        "sortkey_type",
        "sortkeys",
    },
}


def test_target_meta_loads_with_frozen_keys():
    metas = list_target_meta()
    assert set(metas) == set(FROZEN_CONFIG_KEYS)
    for tid, keys in FROZEN_CONFIG_KEYS.items():
        assert keys <= {f.key for f in metas[tid].config_fields}


def test_checksum_is_order_independent():
    t = pa.table(
        {
            "id": pa.array([1, 2, 3], pa.int32()),
            "amt": pa.array([1, None, 3], pa.decimal128(10, 2)),
            "name": pa.array(["a", "b", None]),
        }
    )
    con = duckdb.connect()
    con.register("t1", t)
    con.register("t2", t.take([2, 0, 1]))
    a = con.sql(duckdb_checksum_sql("t1", t.schema)).fetchone()
    b = con.sql(duckdb_checksum_sql("t2", t.schema)).fetchone()
    assert a == b and a[0] == 3


def test_plan_request_defaults():
    req = PlanRequest(tables=[], target_id="bigquery")
    assert req.dq.checksum and req.governance.masking and req.target_mode == "simulated"
