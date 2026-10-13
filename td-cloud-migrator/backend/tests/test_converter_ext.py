import pytest

from app.config_analyser import analyse_config
from app.conversion import convert_all
from app.models import SourceObject
from app.routine_convert import convert_routine
from app.sql_convert import transpile_ex
from tests.test_pipeline import _example_config

TARGETS = ["bigquery", "redshift", "synapse"]


@pytest.fixture(scope="module")
def convs():
    _, objects, order, _ = analyse_config(_example_config())
    out, _ = convert_all(objects, order, TARGETS, {}, "proj")
    return {(c.object_id, c.target): c for c in out}


@pytest.mark.parametrize(("target", "fn"), [("bigquery", "FARM_FINGERPRINT"), ("redshift", "FNV_HASH"), ("synapse", "HASHBYTES")])
def test_hashrow_output_column_uses_target_hash(convs, target, fn):
    c = convs[("VIEW:BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS", target)]
    assert c.status == "converted_with_warnings"
    assert fn in c.sql and "HASHROW" not in c.sql.split("REVIEW REQUIRED")[-1].split("-- Source")[-1]
    assert any("Teradata" in w and "hash" in w.lower() for w in c.warnings)
    assert any("hash" in i.text.lower() for i in c.checklist)


def test_hashrow_in_filter_stays_manual():
    res = transpile_ex("SELECT a FROM DB.T WHERE HASHROW(a) = 5", "bigquery", {})
    assert res.manual


@pytest.mark.parametrize("target", TARGETS)
def test_csum_mavg_become_partitioned_windows(convs, target):
    c = convs[("VIEW:BANKING_DW.VW_BRANCH_PERFORMANCE", target)]
    assert c.status == "converted_with_warnings"
    body = c.sql.upper()
    assert "CSUM(" not in body and "MAVG(" not in body
    assert "PARTITION BY B.BRANCH_ID" in body and "ROWS BETWEEN 2 PRECEDING AND CURRENT ROW" in body
    assert any("PARTITION BY" in i.text for i in c.checklist)


@pytest.mark.parametrize("target", TARGETS)
def test_routines_are_native_and_reviewable(convs, target):
    for oid in (
        "MACRO:BANKING_DW.AML_SCREENING",
        "PROCEDURE:BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS",
        "BTEQ_SCRIPT:BANKING_DW.BTEQ_DAILY_LOAD",
    ):
        c = convs[(oid, target)]
        assert c.status == "converted_with_warnings", (oid, c.reason)
        assert "PROCEDURE" in c.sql and "TODO (manual)" not in c.sql
        assert c.sql.startswith("-- REVIEW REQUIRED") and c.checklist
        assert {i.category for i in c.checklist} >= {"verify", "test"}
    sp = convs[("PROCEDURE:BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS", target)].sql
    assert {"bigquery": "@@row_count", "redshift": "GET DIAGNOSTICS", "synapse": "@@ROWCOUNT"}[target] in sp
    assert {"bigquery": "EXCEPTION WHEN ERROR", "redshift": "EXCEPTION WHEN OTHERS", "synapse": "BEGIN CATCH"}[target] in sp
    assert "ACTIVITY_COUNT" not in sp.split("-- Source")[-1]


@pytest.mark.parametrize("target", TARGETS)
def test_bteq_never_copies_logon(convs, target):
    for oid in ("BTEQ_SCRIPT:BANKING_DW.BTEQ_DAILY_LOAD", "BTEQ_SCRIPT:BANKING_DW.BTEQ_EXTRACT_REPORT"):
        sql = convs[(oid, target)].sql
        assert "etl_svc_acct" not in sql and ".LOGON" not in sql and "TDPROD" not in sql
    ex = convs[("BTEQ_SCRIPT:BANKING_DW.BTEQ_EXTRACT_REPORT", target)].sql
    assert {"bigquery": "EXPORT DATA", "redshift": "UNLOAD", "synapse": "CREATE EXTERNAL TABLE"}[target] in ex


def test_unknown_call_keeps_manual_review():
    obj = SourceObject(
        id="BTEQ_SCRIPT:DB.JOB",
        object_type="bteq_script",
        database="DB",
        name="JOB",
        source_file="job.btq",
        source_format="bteq",
        sql=".LOGON host/user,secret;\nCALL DB.NOT_IN_DUMP(1);\n.QUIT 0;\n",
    )
    c = convert_routine(obj, "bigquery", {}, "", {obj.id: obj})
    assert c.status == "manual_review" and "not in the dump" in (c.reason or "")
    assert "secret" not in c.sql and "user" not in c.sql.lower().split("bigquery")[0]
