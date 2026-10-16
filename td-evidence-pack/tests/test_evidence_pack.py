from datetime import date
from pathlib import Path

import pytest

from evidence_pack.engines import TeradataEmulator
from evidence_pack.pipeline import load_controls, run_candidate
from evidence_pack.reconcile import FAIL, PASS, WAIVED, canonical, fingerprint
from evidence_pack.schema import conform
from evidence_pack.sources import SourceSet, from_dir
from evidence_pack.sqltext import rewrite_calls, split_statements, strip_comments

REPO = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 1, 31)

FAITHFUL_VIEW = """
CREATE OR REPLACE VIEW BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS AS
SELECT ft.TRANSACTION_ID, ft.TRANSACTION_DATE, ft.TRANSACTION_TS, c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME,
       c.KYC_STATUS, a.ACCOUNT_ID, a.ACCOUNT_TYPE, ft.TRANSACTION_TYPE, ft.TRANSACTION_SUBTYPE,
       ft.TRANSACTION_AMOUNT, ft.TRANSACTION_CURRENCY, ft.BASE_CURRENCY_AMOUNT, ft.MERCHANT_NAME,
       ft.COUNTERPARTY_ACCT, ft.IS_INTERNATIONAL, ft.REFERENCE_NUMBER, ft.DESCRIPTION_TEXT, b.BRANCH_NAME, b.REGION,
       CASE WHEN ft.BASE_CURRENCY_AMOUNT >= {threshold} THEN 'THRESHOLD_EXCEEDED'
            WHEN ft.IS_INTERNATIONAL = 1 AND ft.BASE_CURRENCY_AMOUNT >= 25000 THEN 'INTL_THRESHOLD'
            WHEN ft.IS_FLAGGED = 1 THEN 'FLAGGED_SUSPICIOUS' ELSE 'REVIEW' END AS REPORTING_CATEGORY,
       HASH(ft.TRANSACTION_ID, ft.TRANSACTION_DATE) AS ROW_HASH, ft.ETL_BATCH_ID
FROM BANKING_DW.FACT_TRANSACTION ft
JOIN BANKING_DW.DIM_ACCOUNT a ON ft.ACCOUNT_KEY = a.ACCOUNT_KEY AND a.CURRENT_FLAG = 'Y'
JOIN BANKING_DW.DIM_CUSTOMER c ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
LEFT JOIN BANKING_DW.DIM_BRANCH b ON ft.BRANCH_ID = b.BRANCH_ID
WHERE (ft.BASE_CURRENCY_AMOUNT >= {threshold} OR (ft.IS_INTERNATIONAL = 1 AND ft.BASE_CURRENCY_AMOUNT >= 25000)
       OR ft.IS_FLAGGED = 1)
QUALIFY ROW_NUMBER() OVER (PARTITION BY ft.TRANSACTION_ID ORDER BY ft.ETL_BATCH_ID DESC) = 1;
"""


def _candidate(threshold: int) -> SourceSet:
    """Snowflake candidate built from the Teradata tables plus a hand-converted regulatory view."""
    files = {}
    for f in sorted((REPO / "ddl" / "tables").glob("*.sql")):
        files[f"tables/{f.name}"] = _td_table_to_snowflake(f.read_text())
    files["views/02_reg.sql"] = FAITHFUL_VIEW.format(threshold=threshold)
    return SourceSet("test", "test", files)


def _td_table_to_snowflake(sql: str) -> str:
    emu = TeradataEmulator(AS_OF)
    out = []
    for stmt in split_statements(strip_comments(sql)):
        translated = emu.translate(stmt)
        if translated and translated[0] == "TABLE":
            out.append(translated[2].replace("TINYINT", "SMALLINT") + ";")
    return "\n".join(out)


@pytest.fixture(scope="module")
def legacy() -> SourceSet:
    return from_dir("teradata", REPO / "ddl")


def _run(legacy: SourceSet, candidate: SourceSet) -> dict:
    return run_candidate(legacy, candidate, REPO / "data" / "seed", AS_OF, load_controls(None))


def _obj(result: dict, name: str) -> dict:
    return next(o for o in result["objects"] if o["name"] == name)


def test_faithful_conversion_passes_with_hashrow_waiver(legacy):
    result = _run(legacy, _candidate(100000))
    reg = _obj(result, "BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS")
    assert reg["status"] == WAIVED
    assert reg["legacy_rows"] == reg["target_rows"] > 0
    assert all(_obj(result, f"BANKING_DW.{t}")["status"] == PASS for t in ("DIM_CUSTOMER", "FACT_TRANSACTION"))
    assert all(ct["ok"] for ct in reg["control_totals"])


def test_threshold_defect_is_caught_with_business_keys(legacy):
    result = _run(legacy, _candidate(150000))
    reg = _obj(result, "BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS")
    assert reg["status"] == FAIL
    assert reg["missing_in_target"] > 0
    assert any(s["type"] == "missing in target" for s in reg["samples"])
    assert not all(ct["ok"] for ct in reg["control_totals"])
    assert result["verdict"] == FAIL


def test_missing_view_is_an_error(legacy):
    result = _run(legacy, _candidate(100000))
    assert _obj(result, "BANKING_DW.VW_BRANCH_PERFORMANCE")["status"] == "ERROR"


def test_manifest_is_reproducible(legacy):
    a, b = _run(legacy, _candidate(100000)), _run(legacy, _candidate(100000))
    assert a["manifest"]["outputs"] == b["manifest"]["outputs"]
    assert a["manifest"]["manifest_sha256"] == b["manifest"]["manifest_sha256"]


def test_fingerprint_is_order_independent_and_canonical():
    from decimal import Decimal

    assert fingerprint([["1", "a"], ["2", "b"]]) == fingerprint([["2", "b"], ["1", "a"]])
    assert canonical(Decimal("1.50")) == canonical(1.5) == "1.5"
    assert canonical(None) != canonical("")


def test_teradata_rewrites():
    assert rewrite_calls("ZEROIFNULL(NULLIFZERO(x))", "ZEROIFNULL", lambda a: f"COALESCE({a[0]}, 0)") == \
        "COALESCE(NULLIFZERO(x), 0)"
    emu = TeradataEmulator(AS_OF)
    sql = emu._rewrite_query("REPLACE VIEW V AS LOCKING ROW FOR ACCESS SEL CSUM(SUM(x), k) AS c, "
                             "y (FORMAT 'ZZ9') AS y FROM t WHERE d >= CURRENT_DATE - 90")
    assert "SUM(SUM(x)) OVER (ORDER BY k ROWS UNBOUNDED PRECEDING)" in sql
    assert "FORMAT" not in sql and "LOCKING" not in sql
    assert "DATE '2026-01-31'" in sql


@pytest.mark.parametrize(("legacy_t", "target_t", "ok"), [
    ("DECIMAL(15,2)", "NUMBER(15,2)", True),
    ("DECIMAL(15,2)", "NUMBER(15,0)", False),
    ("VARCHAR(50)", "VARCHAR(20)", False),
    ("BYTEINT", "SMALLINT", True),
    ("TIMESTAMP(6)", "TIMESTAMPNTZ(0)", False),
    ("TIMESTAMP(0)", "TIMESTAMP_NTZ(0)", True),
])
def test_declared_type_conformance(legacy_t, target_t, ok):
    assert conform(legacy_t, target_t)[0] is ok
