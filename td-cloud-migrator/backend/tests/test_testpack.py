import time

import sqlglot
from fastapi.testclient import TestClient

from app.main import app

DIALECT = {"bigquery": "bigquery", "redshift": "redshift", "synapse": "tsql"}


def _job(client: TestClient, target: str) -> dict:
    job = client.post(f"/api/examples/banking_dw/run?target={target}").json()
    for _ in range(120):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job.get("analysis") and job.get("status") not in ("queued", "running"):
            return job
        time.sleep(0.25)
    raise AssertionError("example job did not finish")


def test_test_pack_pairs_parse_and_are_bundled():
    client = TestClient(app)
    for target, dialect in DIALECT.items():
        job = _job(client, target)
        convs = {c["object_id"]: c for c in job["analysis"]["conversions"]}
        assert all(c["test_source"] and c["test_target"] for c in convs.values())
        table = convs["TABLE:BANKING_DW.DIM_CUSTOMER"]
        for sql, d in ((table["test_source"], "teradata"), (table["test_target"], dialect)):
            assert "row_count" in sql and "nulls:CUSTOMER_ID" in sql
            sqlglot.parse_one(sql, read=d)
        view = convs["VIEW:BANKING_DW.VW_CUSTOMER_360"]
        sqlglot.parse(view["test_target"], read=dialect)
        assert "AML_SCREENING" in convs["MACRO:BANKING_DW.AML_SCREENING"]["test_source"]
        files = client.get(f"/api/jobs/{job['id']}/outputs").json()
        assert f"{target}/test_pack/teradata_tests.sql" in files
        assert f"{target}/test_pack/{target}_tests.sql" in files
