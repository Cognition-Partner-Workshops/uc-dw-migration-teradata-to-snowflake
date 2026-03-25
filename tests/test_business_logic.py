"""
Category 5: Business Logic Validation (Positive Tests)
Test IDs: B-01 through B-18

Verifies domain values, date logic, SCD2 rules, balance formulas,
regulatory view thresholds, and IS_INTERNATIONAL flag logic.
"""

import datetime

import pytest

from tests.config import DECIMAL_TOLERANCE, DOMAIN_VALUES, SCHEMA_NAME
from tests.utils import run_query


# ---- B-01 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b01_customer_segment_domain(sf_cursor):
    """B-01: Verify CUSTOMER_SEGMENT domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT CUSTOMER_SEGMENT FROM DIM_CUSTOMER")
    actual = {r[0] for r in rows}
    expected = DOMAIN_VALUES["CUSTOMER_SEGMENT"]
    extra = actual - expected
    assert not extra, f"Unexpected CUSTOMER_SEGMENT values: {extra}"


# ---- B-02 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b02_account_type_domain(sf_cursor):
    """B-02: Verify ACCOUNT_TYPE domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT ACCOUNT_TYPE FROM DIM_ACCOUNT")
    actual = {r[0] for r in rows}
    expected = DOMAIN_VALUES["ACCOUNT_TYPE"]
    extra = actual - expected
    assert not extra, f"Unexpected ACCOUNT_TYPE values: {extra}"


# ---- B-03 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b03_account_status_domain(sf_cursor):
    """B-03: Verify ACCOUNT_STATUS domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT ACCOUNT_STATUS FROM DIM_ACCOUNT")
    actual = {r[0] for r in rows}
    expected = DOMAIN_VALUES["ACCOUNT_STATUS"]
    extra = actual - expected
    assert not extra, f"Unexpected ACCOUNT_STATUS values: {extra}"


# ---- B-04 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b04_transaction_type_domain(sf_cursor):
    """B-04: Verify TRANSACTION_TYPE domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT TRANSACTION_TYPE FROM FACT_TRANSACTION")
    actual = {r[0] for r in rows}
    expected = DOMAIN_VALUES["TRANSACTION_TYPE"]
    extra = actual - expected
    assert not extra, f"Unexpected TRANSACTION_TYPE values: {extra}"


# ---- B-05 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b05_channel_domain(sf_cursor):
    """B-05: Verify CHANNEL domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT CHANNEL FROM FACT_TRANSACTION")
    actual = {r[0] for r in rows if r[0] is not None}
    expected = DOMAIN_VALUES["CHANNEL"]
    extra = actual - expected
    assert not extra, f"Unexpected CHANNEL values: {extra}"


# ---- B-06 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b06_kyc_status_domain(sf_cursor):
    """B-06: Verify KYC_STATUS domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT KYC_STATUS FROM DIM_CUSTOMER")
    actual = {r[0] for r in rows if r[0] is not None}
    expected = DOMAIN_VALUES["KYC_STATUS"]
    extra = actual - expected
    assert not extra, f"Unexpected KYC_STATUS values: {extra}"


# ---- B-07 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b07_gender_domain(sf_cursor):
    """B-07: Verify GENDER domain."""
    rows = run_query(sf_cursor, "SELECT DISTINCT GENDER FROM DIM_CUSTOMER")
    actual = {r[0] for r in rows if r[0] is not None}
    expected = DOMAIN_VALUES["GENDER"]
    extra = actual - expected
    assert not extra, f"Unexpected GENDER values: {extra}"


# ---- B-08 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b08_dim_date_range(sf_cursor):
    """B-08: Verify DIM_DATE range is 2000-01-01 to 2029-12-31."""
    rows = run_query(
        sf_cursor,
        "SELECT MIN(CALENDAR_DATE), MAX(CALENDAR_DATE) FROM DIM_DATE",
    )
    min_date, max_date = rows[0]
    assert str(min_date) == "2000-01-01", f"Expected min date 2000-01-01, got {min_date}"
    assert str(max_date) == "2029-12-31", f"Expected max date 2029-12-31, got {max_date}"


# ---- B-09 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b09_date_key_format(sf_cursor):
    """B-09: Verify DATE_KEY format matches YYYYMMDD of CALENDAR_DATE."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE "
        "WHERE DATE_KEY != CAST(TO_CHAR(CALENDAR_DATE, 'YYYYMMDD') AS INTEGER)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} DATE_KEY format mismatches"


# ---- B-10 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b10_snapshot_opening_equals_prior_closing(sf_cursor):
    """B-10: Verify snapshot OPENING_BALANCE = prior month's CLOSING_BALANCE."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT curr "
        "INNER JOIN FACT_MONTHLY_ACCOUNT_SNAPSHOT prev "
        "  ON curr.ACCOUNT_KEY = prev.ACCOUNT_KEY "
        "  AND prev.SNAPSHOT_MONTH_KEY = ("
        "    CASE WHEN curr.SNAPSHOT_MONTH_KEY % 100 = 1 "
        "         THEN (FLOOR(curr.SNAPSHOT_MONTH_KEY / 100) - 1) * 100 + 12 "
        "         ELSE curr.SNAPSHOT_MONTH_KEY - 1 "
        "    END) "
        "WHERE ABS(curr.OPENING_BALANCE - prev.CLOSING_BALANCE) > %s",
        (DECIMAL_TOLERANCE,),
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} rows where OPENING_BALANCE != prior CLOSING_BALANCE"
    )


# ---- B-11 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b11_closing_balance_formula(sf_cursor):
    """B-11: Verify CLOSING_BALANCE = OPENING + CREDITS - DEBITS."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT "
        "WHERE ABS(CLOSING_BALANCE - (OPENING_BALANCE + TOTAL_CREDITS - TOTAL_DEBITS)) > %s",
        (DECIMAL_TOLERANCE,),
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} rows violating balance formula"
    )


# ---- B-12 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b12_regulatory_view_threshold_logic(sf_cursor):
    """B-12: Verify VW_REGULATORY_LARGE_TRANSACTIONS filters correctly."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM VW_REGULATORY_LARGE_TRANSACTIONS "
        "WHERE BASE_CURRENCY_AMOUNT < 100000 "
        "  AND NOT (IS_INTERNATIONAL = 1 AND BASE_CURRENCY_AMOUNT >= 25000) "
        "  AND IS_FLAGGED != 1",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} rows violating regulatory thresholds"
    )


# ---- B-13 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b13_is_international_flag_logic(sf_cursor):
    """B-13: Non-NOK currency should have IS_INTERNATIONAL = 1."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION "
        "WHERE TRANSACTION_CURRENCY != 'NOK' AND IS_INTERNATIONAL != 1",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} non-NOK transactions with IS_INTERNATIONAL != 1"
    )


# ---- B-14 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b14_scd2_one_current_per_natural_key(sf_cursor):
    """B-14: Exactly one CURRENT_FLAG='Y' per natural CUSTOMER_ID."""
    rows = run_query(
        sf_cursor,
        "SELECT CUSTOMER_ID, COUNT(*) AS CNT "
        "FROM DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y' "
        "GROUP BY CUSTOMER_ID HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, (
        f"Found {len(rows)} CUSTOMER_IDs with multiple current records"
    )


# ---- B-15 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b15_effective_from_before_effective_to(sf_cursor):
    """B-15: EFFECTIVE_FROM < EFFECTIVE_TO for both DIM_CUSTOMER and DIM_ACCOUNT."""
    for table in ("DIM_CUSTOMER", "DIM_ACCOUNT"):
        rows = run_query(
            sf_cursor,
            f"SELECT COUNT(*) FROM {table} WHERE EFFECTIVE_FROM >= EFFECTIVE_TO",
        )
        assert rows[0][0] == 0, (
            f"{table}: found {rows[0][0]} rows with EFFECTIVE_FROM >= EFFECTIVE_TO"
        )


# ---- B-16 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b16_currency_code_domain(sf_cursor):
    """B-16: Verify CURRENCY_CODE domain in DIM_ACCOUNT."""
    rows = run_query(sf_cursor, "SELECT DISTINCT CURRENCY_CODE FROM DIM_ACCOUNT")
    actual = {r[0] for r in rows}
    expected = DOMAIN_VALUES["CURRENCY_CODE"]
    extra = actual - expected
    assert not extra, f"Unexpected CURRENCY_CODE values: {extra}"


# ---- B-17 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b17_branch_type_domain(sf_cursor):
    """B-17: Verify BRANCH_TYPE domain in DIM_BRANCH."""
    rows = run_query(sf_cursor, "SELECT DISTINCT BRANCH_TYPE FROM DIM_BRANCH")
    actual = {r[0] for r in rows if r[0] is not None}
    expected = DOMAIN_VALUES["BRANCH_TYPE"]
    extra = actual - expected
    assert not extra, f"Unexpected BRANCH_TYPE values: {extra}"


# ---- B-18 -----------------------------------------------------------------
@pytest.mark.business_logic
def test_b18_region_domain(sf_cursor):
    """B-18: Verify REGION domain in DIM_BRANCH."""
    rows = run_query(sf_cursor, "SELECT DISTINCT REGION FROM DIM_BRANCH")
    actual = {r[0] for r in rows if r[0] is not None}
    expected = DOMAIN_VALUES["REGION"]
    extra = actual - expected
    assert not extra, f"Unexpected REGION values: {extra}"
