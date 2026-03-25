"""
Category 3: Data Integrity & Checksum Tests (Positive Tests)
Test IDs: D-01 through D-13

Verifies aggregate checksums, duplicate detection, SCD2 consistency,
and decimal precision preservation.
"""

import pytest

from tests.config import DECIMAL_TOLERANCE, SCHEMA_NAME
from tests.utils import run_query


# ---- D-01 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d01_dim_customer_aggregate_checksum(sf_cursor):
    """D-01: Verify DIM_CUSTOMER aggregate checksum."""
    rows = run_query(
        sf_cursor,
        "SELECT "
        "  COUNT(*) AS ROW_COUNT, "
        "  COUNT(DISTINCT CUSTOMER_ID) AS DISTINCT_CUSTOMERS, "
        "  MIN(ONBOARDING_DATE) AS MIN_ONBOARD, "
        "  MAX(ONBOARDING_DATE) AS MAX_ONBOARD, "
        "  SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END) AS ACTIVE_COUNT "
        "FROM DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y'",
    )
    row = rows[0]
    row_count, distinct_cust, min_date, max_date, active_count = row

    assert row_count > 0, "DIM_CUSTOMER (current) has 0 rows"
    assert distinct_cust == row_count, (
        "Distinct CUSTOMER_ID != row count for current records"
    )
    assert active_count > 0, "No active customers"
    assert min_date is not None and max_date is not None, "Date range is NULL"


# ---- D-02 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d02_fact_transaction_monthly_checksum(sf_cursor):
    """D-02: Verify FACT_TRANSACTION aggregate checksum per month."""
    rows = run_query(
        sf_cursor,
        "SELECT "
        "  EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR, "
        "  EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH, "
        "  COUNT(*) AS TXN_COUNT, "
        "  SUM(TRANSACTION_AMOUNT) AS TOTAL_AMOUNT, "
        "  SUM(BASE_CURRENCY_AMOUNT) AS TOTAL_BASE_AMOUNT "
        "FROM FACT_TRANSACTION "
        "GROUP BY 1, 2 ORDER BY 1, 2",
    )
    assert len(rows) > 0, "No monthly aggregates found"
    for year, month, count, total_amt, total_base in rows:
        assert count > 0, f"Month {int(year)}-{int(month):02d} has 0 transactions"
        # total_amt can be negative (net debits) so just check it's not NULL
        assert total_amt is not None, f"NULL TRANSACTION_AMOUNT sum for {int(year)}-{int(month):02d}"


# ---- D-03 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d03_monthly_snapshot_balance_totals(sf_cursor):
    """D-03: Verify monthly snapshot balance totals."""
    rows = run_query(
        sf_cursor,
        "SELECT SNAPSHOT_MONTH_KEY, "
        "  SUM(CLOSING_BALANCE) AS TOTAL_CLOSING, "
        "  SUM(TOTAL_DEBITS) AS TOTAL_DEBITS, "
        "  SUM(TOTAL_CREDITS) AS TOTAL_CREDITS "
        "FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT "
        "GROUP BY 1 ORDER BY 1",
    )
    assert len(rows) > 0, "No snapshot months found"
    for month_key, closing, debits, credits_ in rows:
        assert closing is not None, f"NULL closing balance for {month_key}"
        assert debits is not None, f"NULL debits for {month_key}"
        assert credits_ is not None, f"NULL credits for {month_key}"


# ---- D-04 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d04_no_duplicate_customer_keys(sf_cursor):
    """D-04: Verify no duplicate primary keys in DIM_CUSTOMER."""
    rows = run_query(
        sf_cursor,
        "SELECT CUSTOMER_KEY, COUNT(*) AS CNT "
        "FROM DIM_CUSTOMER GROUP BY CUSTOMER_KEY HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, f"Found {len(rows)} duplicate CUSTOMER_KEYs: {rows[:5]}"


# ---- D-05 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d05_no_duplicate_account_keys(sf_cursor):
    """D-05: Verify no duplicate primary keys in DIM_ACCOUNT."""
    rows = run_query(
        sf_cursor,
        "SELECT ACCOUNT_KEY, COUNT(*) AS CNT "
        "FROM DIM_ACCOUNT GROUP BY ACCOUNT_KEY HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, f"Found {len(rows)} duplicate ACCOUNT_KEYs: {rows[:5]}"


# ---- D-06 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d06_no_duplicate_transaction_ids(sf_cursor):
    """D-06: Verify no duplicate TRANSACTION_IDs."""
    rows = run_query(
        sf_cursor,
        "SELECT TRANSACTION_ID, COUNT(*) AS CNT "
        "FROM FACT_TRANSACTION GROUP BY TRANSACTION_ID HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, f"Found {len(rows)} duplicate TRANSACTION_IDs: {rows[:5]}"


# ---- D-07 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d07_onboarding_date_range(sf_cursor):
    """D-07: Verify MIN/MAX ONBOARDING_DATE ranges."""
    rows = run_query(
        sf_cursor,
        "SELECT MIN(ONBOARDING_DATE), MAX(ONBOARDING_DATE) FROM DIM_CUSTOMER",
    )
    min_date, max_date = rows[0]
    assert min_date is not None, "MIN ONBOARDING_DATE is NULL"
    assert max_date is not None, "MAX ONBOARDING_DATE is NULL"
    assert min_date < max_date, "MIN >= MAX for ONBOARDING_DATE"


# ---- D-08 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d08_transaction_date_range(sf_cursor):
    """D-08: Verify MIN/MAX TRANSACTION_DATE ranges."""
    rows = run_query(
        sf_cursor,
        "SELECT MIN(TRANSACTION_DATE), MAX(TRANSACTION_DATE) FROM FACT_TRANSACTION",
    )
    min_date, max_date = rows[0]
    assert min_date is not None, "MIN TRANSACTION_DATE is NULL"
    assert max_date is not None, "MAX TRANSACTION_DATE is NULL"
    assert min_date < max_date, "MIN >= MAX for TRANSACTION_DATE"


# ---- D-09 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d09_scd2_current_flag_consistency(sf_cursor):
    """D-09: Verify SCD2 current flag consistency — at most one Y per CUSTOMER_ID."""
    rows = run_query(
        sf_cursor,
        "SELECT CUSTOMER_ID, COUNT(*) AS CNT "
        "FROM DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y' "
        "GROUP BY CUSTOMER_ID HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, (
        f"Found {len(rows)} CUSTOMER_IDs with multiple CURRENT_FLAG='Y': {rows[:5]}"
    )


# ---- D-10 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d10_decimal_precision_preserved(sf_cursor):
    """D-10: Verify DECIMAL precision preserved for monetary columns."""
    rows = run_query(
        sf_cursor,
        "SELECT "
        "  SUM(TRANSACTION_AMOUNT) AS SUM_AMT, "
        "  AVG(TRANSACTION_AMOUNT) AS AVG_AMT, "
        "  MIN(TRANSACTION_AMOUNT) AS MIN_AMT, "
        "  MAX(TRANSACTION_AMOUNT) AS MAX_AMT "
        "FROM FACT_TRANSACTION",
    )
    sum_amt, avg_amt, min_amt, max_amt = rows[0]
    # All aggregates should be non-NULL
    for label, val in [("SUM", sum_amt), ("AVG", avg_amt), ("MIN", min_amt), ("MAX", max_amt)]:
        assert val is not None, f"{label}(TRANSACTION_AMOUNT) is NULL"

    # Verify that DECIMAL(15,2) values round-trip without precision loss
    precision_rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION "
        "WHERE TRANSACTION_AMOUNT != ROUND(TRANSACTION_AMOUNT, 2)",
    )
    assert precision_rows[0][0] == 0, "TRANSACTION_AMOUNT has values beyond 2 decimal places"


# ---- D-11 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d11_no_full_row_duplicates_dim_product(sf_cursor):
    """D-11: Verify no duplicate rows in SET-table equivalents (DIM_PRODUCT)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM ("
        "  SELECT PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_CATEGORY, "
        "         PRODUCT_SUBCATEGORY, BASE_INTEREST_RATE, MIN_BALANCE, MAX_BALANCE, "
        "         FEE_STRUCTURE, MONTHLY_FEE, IS_REGULATED, REGULATORY_CODE, "
        "         LAUNCH_DATE, DISCONTINUE_DATE, IS_ACTIVE, ETL_BATCH_ID, ETL_INSERT_TS "
        "  FROM DIM_PRODUCT GROUP BY ALL HAVING COUNT(*) > 1"
        ")",
    )
    assert rows[0][0] == 0, "Full-row duplicates found in DIM_PRODUCT (SET table violation)"


# ---- D-12 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d12_dim_product_aggregate_checksum(sf_cursor):
    """D-12: Verify DIM_PRODUCT aggregate checksum."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*), COUNT(DISTINCT PRODUCT_CODE), "
        "  SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END) "
        "FROM DIM_PRODUCT",
    )
    row_count, distinct_products, active_count = rows[0]
    assert row_count == 10, f"Expected 10 products, got {row_count}"
    assert distinct_products == row_count, "Duplicate PRODUCT_CODEs found"
    assert active_count > 0, "No active products"


# ---- D-13 -----------------------------------------------------------------
@pytest.mark.data_integrity
def test_d13_dim_branch_aggregate_checksum(sf_cursor):
    """D-13: Verify DIM_BRANCH aggregate checksum."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*), COUNT(DISTINCT BRANCH_CODE), COUNT(DISTINCT REGION) "
        "FROM DIM_BRANCH",
    )
    row_count, distinct_branches, distinct_regions = rows[0]
    assert row_count == 14, f"Expected 14 branches, got {row_count}"
    assert distinct_branches == row_count, "Duplicate BRANCH_CODEs found"
    assert distinct_regions == 5, f"Expected 5 regions, got {distinct_regions}"
