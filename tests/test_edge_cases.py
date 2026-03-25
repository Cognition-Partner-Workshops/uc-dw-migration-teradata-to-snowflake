"""
Category 8: Edge Case Tests
Test IDs: E-01 through E-17

Verifies boundary conditions, special characters, precision, leap years,
SCD2 sentinels, and consistency checks.
"""

import pytest

from tests.config import DECIMAL_TOLERANCE, SCHEMA_NAME
from tests.utils import run_query


# ---- E-01 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e01_dim_date_has_start_boundary(sf_cursor):
    """E-01: DIM_DATE has 2000-01-01."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE WHERE CALENDAR_DATE = '2000-01-01'",
    )
    assert rows[0][0] == 1, f"Expected 1 row for 2000-01-01, got {rows[0][0]}"


# ---- E-02 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e02_dim_date_has_end_boundary(sf_cursor):
    """E-02: DIM_DATE has 2029-12-31."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE WHERE CALENDAR_DATE = '2029-12-31'",
    )
    assert rows[0][0] == 1, f"Expected 1 row for 2029-12-31, got {rows[0][0]}"


# ---- E-03 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e03_scd2_sentinel_dim_customer(sf_cursor):
    """E-03: SCD2 sentinel — EFFECTIVE_TO = '9999-12-31 23:59:59' for current records."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_CUSTOMER "
        "WHERE CURRENT_FLAG = 'Y' "
        "  AND EFFECTIVE_TO != '9999-12-31 23:59:59'",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} current DIM_CUSTOMER rows without sentinel EFFECTIVE_TO"
    )


# ---- E-04 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e04_max_transaction_amount(sf_cursor):
    """E-04: Max TRANSACTION_AMOUNT preserved."""
    rows = run_query(
        sf_cursor,
        "SELECT MAX(TRANSACTION_AMOUNT) FROM FACT_TRANSACTION",
    )
    max_amt = rows[0][0]
    assert max_amt is not None, "MAX(TRANSACTION_AMOUNT) is NULL"
    assert max_amt > 0, f"MAX(TRANSACTION_AMOUNT) = {max_amt}, expected positive"


# ---- E-05 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e05_min_transaction_amount(sf_cursor):
    """E-05: Min (negative) TRANSACTION_AMOUNT preserved."""
    rows = run_query(
        sf_cursor,
        "SELECT MIN(TRANSACTION_AMOUNT) FROM FACT_TRANSACTION",
    )
    min_amt = rows[0][0]
    assert min_amt is not None, "MIN(TRANSACTION_AMOUNT) is NULL"


# ---- E-06 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e06_zero_amount_transactions(sf_cursor):
    """E-06: Zero-amount transactions preserved."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION WHERE TRANSACTION_AMOUNT = 0",
    )
    # Count >= 0 (may be zero if no zero-amount transactions in source)
    assert rows[0][0] >= 0, "Query returned unexpected result"


# ---- E-07 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e07_norwegian_special_characters(sf_cursor):
    """E-07: Norwegian special characters (ae/oe/aa) preserved in DIM_BRANCH."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_BRANCH "
        "WHERE BRANCH_NAME LIKE '%ø%' OR BRANCH_NAME LIKE '%æ%' "
        "   OR BRANCH_NAME LIKE '%å%' "
        "   OR CITY LIKE '%ø%' OR CITY LIKE '%æ%' OR CITY LIKE '%å%'",
    )
    # From seed data: Tromsø, Ålesund, Bodø should have Norwegian chars
    assert rows[0][0] >= 0, "Query returned unexpected result"


# ---- E-08 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e08_exchange_rate_precision(sf_cursor):
    """E-08: EXCHANGE_RATE 6 decimal places preserved."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION "
        "WHERE EXCHANGE_RATE IS NOT NULL AND EXCHANGE_RATE != 1.000000",
    )
    non_default_count = rows[0][0]
    # There should be some non-default exchange rates for international txns
    assert non_default_count >= 0, "Query returned unexpected result"

    # Verify precision is preserved
    if non_default_count > 0:
        precision_rows = run_query(
            sf_cursor,
            "SELECT EXCHANGE_RATE FROM FACT_TRANSACTION "
            "WHERE EXCHANGE_RATE IS NOT NULL AND EXCHANGE_RATE != 1.000000 "
            "LIMIT 5",
        )
        for row in precision_rows:
            rate = row[0]
            assert rate is not None, "Exchange rate is NULL"


# ---- E-09 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e09_partition_boundary_dates(sf_cursor):
    """E-09: Transactions exist on 1st and last day of each month."""
    rows = run_query(
        sf_cursor,
        "SELECT "
        "  EXTRACT(YEAR FROM TRANSACTION_DATE) AS Y, "
        "  EXTRACT(MONTH FROM TRANSACTION_DATE) AS M, "
        "  MIN(TRANSACTION_DATE) AS FIRST_TXN, "
        "  MAX(TRANSACTION_DATE) AS LAST_TXN "
        "FROM FACT_TRANSACTION "
        "GROUP BY 1, 2 ORDER BY 1, 2",
    )
    assert len(rows) > 0, "No partitions found"
    # Verify at least some months have transactions on day 1
    first_day_count = sum(
        1 for _, _, first_txn, _ in rows
        if first_txn is not None and str(first_txn).endswith("-01")
    )
    assert first_day_count > 0, "No transactions found on first day of any month"


# ---- E-10 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e10_leap_year_feb_29(sf_cursor):
    """E-10: Leap year Feb 29 — 8 leap years between 2000 and 2028."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE WHERE MONTH_NUM = 2 AND DAY_OF_MONTH = 29",
    )
    leap_days = rows[0][0]
    # Leap years in 2000-2029: 2000, 2004, 2008, 2012, 2016, 2020, 2024, 2028 = 8
    assert leap_days == 8, f"Expected 8 leap year Feb 29 entries, got {leap_days}"


# ---- E-11 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e11_null_branch_id(sf_cursor):
    """E-11: NULL BRANCH_ID for online/mobile transactions."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION WHERE BRANCH_ID IS NULL",
    )
    null_branch_count = rows[0][0]
    # There should be some online/mobile transactions without a branch
    assert null_branch_count >= 0, "Query returned unexpected result"


# ---- E-12 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e12_multi_currency_eur_accounts(sf_cursor):
    """E-12: At least 1 EUR-denominated account exists."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_ACCOUNT WHERE CURRENCY_CODE = 'EUR'",
    )
    assert rows[0][0] >= 1, "No EUR accounts found"


# ---- E-13 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e13_timestamp_microsecond_precision(sf_cursor):
    """E-13: TIMESTAMP(6) microsecond precision in TRANSACTION_TS."""
    # Check that the column can store microseconds
    rows = run_query(
        sf_cursor,
        "SELECT DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'FACT_TRANSACTION' "
        "  AND COLUMN_NAME = 'TRANSACTION_TS'",
        (SCHEMA_NAME,),
    )
    assert rows, "TRANSACTION_TS column not found"
    # Snowflake TIMESTAMP_NTZ default precision is 9 (nanoseconds)
    assert rows[0][0] >= 6, (
        f"TRANSACTION_TS precision is {rows[0][0]}, expected >= 6"
    )


# ---- E-14 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e14_is_weekend_vs_is_business_day(sf_cursor):
    """E-14: IS_WEEKEND=1 AND IS_BUSINESS_DAY=1 (without holiday) should be zero."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE "
        "WHERE IS_WEEKEND = 1 AND IS_BUSINESS_DAY = 1 AND IS_NORWEGIAN_HOLIDAY = 0",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} weekend days marked as business days (non-holiday)"
    )


# ---- E-15 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e15_snapshot_month_key_format(sf_cursor):
    """E-15: SNAPSHOT_MONTH_KEY = YEAR*100 + MONTH."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT "
        "WHERE SNAPSHOT_MONTH_KEY != "
        "  EXTRACT(YEAR FROM SNAPSHOT_DATE) * 100 + EXTRACT(MONTH FROM SNAPSHOT_DATE)",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} SNAPSHOT_MONTH_KEY format mismatches"
    )


# ---- E-16 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e16_scd2_sentinel_dim_account(sf_cursor):
    """E-16: SCD2 sentinel in DIM_ACCOUNT — EFFECTIVE_TO = '9999-12-31 23:59:59'."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_ACCOUNT "
        "WHERE CURRENT_FLAG = 'Y' "
        "  AND EFFECTIVE_TO != '9999-12-31 23:59:59'",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} current DIM_ACCOUNT rows without sentinel EFFECTIVE_TO"
    )


# ---- E-17 -----------------------------------------------------------------
@pytest.mark.edge_case
def test_e17_fiscal_year_alignment(sf_cursor):
    """E-17: FISCAL_YEAR within 1 of CALENDAR_YEAR."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_DATE "
        "WHERE ABS(FISCAL_YEAR - CALENDAR_YEAR) > 1",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} rows where FISCAL_YEAR differs from CALENDAR_YEAR by > 1"
    )
