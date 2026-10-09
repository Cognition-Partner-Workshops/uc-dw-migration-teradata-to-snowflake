import gzip
import io
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config_analyser import analyse_config
from app.conversion import convert_all
from app.data_analyser import analyse_data
from app.ingest import UploadedFile, expand
from app.main import app
from app.models import DataOptions
from app.sql_convert import preprocess, transpile_query

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "banking_dw"
client = TestClient(app)


def _example_config(name: str = "config_dump.zip") -> list[UploadedFile]:
    return expand([(name, (EXAMPLE / name).read_bytes())])


@pytest.fixture(scope="module")
def analysed():
    return analyse_config(_example_config())


def test_config_inventory_and_create_order(analysed):
    _, objects, order, msgs = analysed
    kinds = Counter(o.object_type for o in objects)
    assert kinds == {"table": 7, "view": 3, "macro": 3, "procedure": 3, "bteq_script": 2}
    assert not msgs
    pos = {oid: i for i, oid in enumerate(order)}
    for o in objects:
        for dep in o.dependencies:
            assert pos[dep] < pos[o.id], f"{dep} must be created before {o.id}"
    acct = next(o for o in objects if o.name == "DIM_ACCOUNT").table
    assert acct.column("ACCOUNT_KEY").identity is not None
    assert acct.partition_columns == ["OPENING_DATE"] and acct.statistics


def test_dbc_export_matches_ddl(analysed):
    _, ddl_objects, _, _ = analysed
    _, objects, _, msgs = analyse_config(_example_config("config_dump_dbc.zip"))
    assert not msgs
    ddl = {o.name: o.table for o in ddl_objects if o.table}
    dbc = {o.name: o.table for o in objects if o.table}
    assert set(dbc) == set(ddl)
    for name, t in dbc.items():
        assert [c.td_type for c in t.columns] == [c.td_type for c in ddl[name].columns], name
        assert [c.default for c in t.columns] == [c.default for c in ddl[name].columns], name
        assert t.primary_index == ddl[name].primary_index
    assert sum(o.object_type == "view" for o in objects) == 3


def test_conversion_statuses(analysed):
    _, objects, order, _ = analysed
    convs, mappings = convert_all(objects, order, ["bigquery", "redshift", "synapse"], {}, "proj")
    by = {(c.object_id, c.target): c for c in convs}
    for t in ("bigquery", "redshift", "synapse"):
        assert by[("TABLE:BANKING_DW.FACT_TRANSACTION", t)].status.startswith("converted")
        assert by[("VIEW:BANKING_DW.VW_CUSTOMER_360", t)].status.startswith("converted")
        assert by[("VIEW:BANKING_DW.VW_BRANCH_PERFORMANCE", t)].status == "manual_review"
        assert by[("PROCEDURE:BANKING_DW.SP_MONTHLY_SNAPSHOT", t)].status == "manual_review"
        assert mappings[t]["TABLE:BANKING_DW.DIM_DATE"]
    assert "CLUSTER BY ACCOUNT_KEY" in by[("TABLE:BANKING_DW.FACT_TRANSACTION", "bigquery")].sql
    assert "DISTKEY (account_key)" in by[("TABLE:BANKING_DW.FACT_TRANSACTION", "redshift")].sql
    assert "DISTRIBUTION = HASH([ACCOUNT_KEY])" in by[("TABLE:BANKING_DW.FACT_TRANSACTION", "synapse")].sql
    v = by[("VIEW:BANKING_DW.VW_CUSTOMER_360", "synapse")].sql
    assert "QUALIFY" not in v and "ZEROIFNULL" not in v and "LOCKING" not in v


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("bigquery", "DATE_ADD(CURRENT_DATE, INTERVAL -3 MONTH)"),
        ("redshift", "DATEADD(MONTH, -3, CURRENT_DATE)"),
        ("synapse", "DATEADD(MONTH, -3, GETDATE())"),
    ],
)
def test_teradata_rewrites(target, expected):
    pre, rules, _ = preprocess("LOCKING ROW FOR ACCESS SEL ZEROIFNULL(a) (FORMAT 'ZZ9') AS x, ADD_MONTHS(CURRENT_DATE, -3) AS d FROM DB.T")
    assert "SEL -> SELECT" in rules
    out, _ = transpile_query(pre, target, {}, "")
    assert "COALESCE(a, 0)" in out and expected in out and "FORMAT" not in out


def test_data_mapping_header_and_rejects(analysed):
    _, objects, _, _ = analysed
    tables = {o.id: o.table for o in objects if o.table}
    good = "ACCOUNT_KEY|TRANSACTION_ID|TRANSACTION_DATE|CUSTOMER_KEY|PRODUCT_ID|DATE_KEY|TRANSACTION_TYPE|TRANSACTION_AMOUNT\n"
    rows = ["1|10|2025-01-01|1|1|20250101|DEBIT|10.00", "2|11|2025-13-01|1|1|20250101|DEBIT|1.00", "|12|2025-01-02|1|1|20250102|DEBIT|2.00"]
    files = [
        UploadedFile("exports/fact_transaction_0001.psv", (good + "\n".join(rows)).encode()),
        UploadedFile("exports/fact_transaction_0002.csv.gz", gzip.compress(b"3,13,2025-01-03,1,1,20250103,CREDIT,5.5\n")),
        UploadedFile("exports/unknown_thing.csv", b"A,B\n1,2\n"),
    ]
    _, data, plans, _, _ = analyse_data(files, tables, DataOptions())
    by = {d.path: d for d in data}
    assert by["exports/fact_transaction_0001.psv"].delimiter == "|" and by["exports/fact_transaction_0001.psv"].has_header
    assert by["exports/unknown_thing.csv"].table_id is None
    r = plans["TABLE:BANKING_DW.FACT_TRANSACTION"].readiness
    assert len(r.files) == 2  # headerless part 2 reuses the column layout of part 1
    assert r.total_rows == 4 and r.rejected_rows == 2


def test_api_example_end_to_end():
    job = client.post("/api/examples/banking_dw/run").json()
    assert job["status"] == "analysed", job.get("error")
    readiness = {r["table_id"]: r for r in job["analysis"]["readiness"]}
    assert readiness["TABLE:BANKING_DW.FACT_TRANSACTION"]["rejected_rows"] == 3
    assert readiness["TABLE:BANKING_DW.DIM_DATE"]["total_rows"] == 731
    job = client.post(f"/api/jobs/{job['id']}/load", json={"targets": ["bigquery", "synapse"]}).json()
    for target in ("bigquery", "synapse"):
        res = job["loads"][target]
        assert res["status"] != "failed"
        tables = {t["table_id"]: t for t in res["tables"]}
        assert tables["TABLE:BANKING_DW.DIM_CUSTOMER"]["loaded_rows"] == 15
        assert tables["TABLE:BANKING_DW.FACT_TRANSACTION"]["loaded_rows"] == 597
        assert all(t["checks_passed"] == t["checks_total"] for t in res["tables"])
        assert all(v["created"] for v in res["views"])
    bundle = client.get(f"/api/jobs/{job['id']}/bundle.zip")
    names = zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()
    for f in (
        "conversion_report.md",
        "mapping_report.csv",
        "data_loading_instructions.md",
        "bigquery/load/load_data.sh",
        "redshift/load/copy.sql",
        "synapse/load/copy_into.sql",
    ):
        assert f"migration_output/{f}" in names


def test_api_upload_and_override():
    cfg = (EXAMPLE / "config_dump.zip").read_bytes()
    data = b"BRANCH_ID|BRANCH_CODE|BRANCH_NAME|BRANCH_TYPE|CITY|REGION|COUNTRY_CODE|OPENING_DATE|IS_ACTIVE\n1|B1|One|FULL|Oslo|EAST|NOR|2020-01-01|1\n"
    r = client.post(
        "/api/jobs",
        files=[("config_files", ("cfg.zip", cfg)), ("data_files", ("offices.txt", data))],
        data={"options": '{"targets": ["redshift"]}'},
    )
    job = r.json()
    assert r.status_code == 200 and job["options"]["targets"] == ["redshift"]
    f = next(d for d in job["analysis"]["data"] if d["path"] == "offices.txt")
    assert f["table_id"] == "TABLE:BANKING_DW.DIM_BRANCH" and f["match_method"] == "fuzzy"
    job = client.post(f"/api/jobs/{job['id']}/mappings", json={"overrides": {"offices.txt": "TABLE:BANKING_DW.DIM_PRODUCT"}}).json()
    f = next(d for d in job["analysis"]["data"] if d["path"] == "offices.txt")
    assert f["table_id"] == "TABLE:BANKING_DW.DIM_PRODUCT" and f["match_method"] == "manual"
    assert client.post("/api/jobs", data={"options": "{}"}).status_code == 422


def test_zip_path_traversal_is_neutralised():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../etc/evil.sql", "SELECT 1;")
    assert [f.path for f in expand([("x.zip", buf.getvalue())])] == ["etc/evil.sql"]


def test_api_rejects_corrupt_zip_with_message():
    r = client.post("/api/jobs", files=[("config_files", ("broken.zip", b"not a zip"))], data={"options": "{}"})
    assert r.status_code == 422 and "not a valid ZIP archive" in r.json()["detail"]


def test_selected_format_mismatch_is_reported(analysed):
    _, objects, _, _ = analysed
    tables = {o.id: o.table for o in objects if o.table}
    f = UploadedFile("dim_branch.csv", b"BRANCH_ID|BRANCH_CODE\n1|B1\n")
    _, data, _, _, _ = analyse_data([f], tables, DataOptions(data_format="parquet"))
    assert data[0].format == "delimited"
    assert any("Selected format is parquet" in i for i in data[0].issues)
