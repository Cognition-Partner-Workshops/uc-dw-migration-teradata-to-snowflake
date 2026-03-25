"""
Category 9: View Parity Tests
Test IDs: V-01 through V-06

Verifies that the three migrated views return data, contain expected
columns, and enforce their business rules correctly.
"""

import pytest

from tests.config import SCHEMA_NAME
from tests.utils import run_query


# ---- V-01 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v01_vw_customer_360_returns_data(sf_cursor):
    """V-01: VW_CUSTOMER_360 returns data."""
    rows = run_query(sf_cursor, "SELECT COUNT(*) FROM VW_CUSTOMER_360")
    assert rows[0][0] > 0, "VW_CUSTOMER_360 returned 0 rows"


# ---- V-02 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v02_vw_customer_360_column_completeness(sf_cursor):
    """V-02: VW_CUSTOMER_360 has all expected columns."""
    expected_columns = {
        "CUSTOMER_ID", "FULL_NAME", "CUSTOMER_SEGMENT", "RISK_SCORE",
        "CREDIT_RATING", "KYC_STATUS", "ONBOARDING_DATE", "TENURE_YEARS",
        "TOTAL_ACCOUNTS", "ACTIVE_ACCOUNTS", "TOTAL_BALANCE",
        "TXN_COUNT_LAST_90_DAYS", "TXN_AMOUNT_LAST_90_DAYS",
        "LAST_TXN_DATE", "PRIMARY_CHANNEL", "CITY", "COUNTRY_CODE",
    }
    rows = run_query(
        sf_cursor,
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'VW_CUSTOMER_360'",
        (SCHEMA_NAME,),
    )
    actual_columns = {r[0] for r in rows}
    missing = expected_columns - actual_columns
    assert not missing, f"VW_CUSTOMER_360 missing columns: {missing}"


# ---- V-03 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v03_regulatory_view_threshold_filtering(sf_cursor):
    """V-03: VW_REGULATORY_LARGE_TRANSACTIONS — all rows meet thresholds."""
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


# ---- V-04 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v04_regulatory_view_deduplication(sf_cursor):
    """V-04: VW_REGULATORY_LARGE_TRANSACTIONS — no duplicate TRANSACTION_IDs."""
    rows = run_query(
        sf_cursor,
        "SELECT TRANSACTION_ID, COUNT(*) AS CNT "
        "FROM VW_REGULATORY_LARGE_TRANSACTIONS "
        "GROUP BY TRANSACTION_ID HAVING COUNT(*) > 1",
    )
    assert len(rows) == 0, (
        f"Found {len(rows)} duplicate TRANSACTION_IDs in regulatory view"
    )


# ---- V-05 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v05_branch_performance_active_branches(sf_cursor):
    """V-05: VW_BRANCH_PERFORMANCE — distinct BRANCH_ID matches active branches."""
    perf_rows = run_query(
        sf_cursor,
        "SELECT COUNT(DISTINCT BRANCH_ID) FROM VW_BRANCH_PERFORMANCE",
    )
    active_rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_BRANCH WHERE IS_ACTIVE = 1",
    )
    perf_count = perf_rows[0][0]
    active_count = active_rows[0][0]
    # The view should have branches <= active branch count
    # (some active branches may have no snapshots in the 24-month window)
    assert perf_count <= active_count, (
        f"View has {perf_count} branches but only {active_count} are active"
    )
    assert perf_count > 0, "VW_BRANCH_PERFORMANCE has no branches"


# ---- V-06 -----------------------------------------------------------------
@pytest.mark.view_parity
def test_v06_branch_performance_cumulative_fees(sf_cursor):
    """V-06: VW_BRANCH_PERFORMANCE — CUMULATIVE_FEES_YTD should not be negative."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM VW_BRANCH_PERFORMANCE "
        "WHERE CUMULATIVE_FEES_YTD < 0",
    )
    assert rows[0][0] == 0, (
        f"Found {rows[0][0]} rows with negative CUMULATIVE_FEES_YTD"
    )
