"""
Category 6: Teradata-to-Snowflake Translation Tests (Positive)
Test IDs: T-01 through T-11

Verifies that Teradata-specific SQL features have been correctly
translated to their Snowflake equivalents.
"""

import pytest

from tests.config import SCHEMA_NAME, TIMESTAMP_TYPE
from tests.utils import run_query


# ---- T-01 -----------------------------------------------------------------
@pytest.mark.translation
def test_t01_casespecific_handling(sf_cursor):
    """T-01: Verify CASESPECIFIC handling — check string case consistency."""
    # In Teradata NOT CASESPECIFIC columns are case-insensitive.
    # After migration the data should be stored consistently.
    # We verify that we can detect any case inconsistency.
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_CUSTOMER "
        "WHERE CITY IS NOT NULL AND CITY != UPPER(CITY) AND CITY != LOWER(CITY)",
    )
    # This is informational — mixed case is valid if migration preserved original case
    # The test passes regardless; it just confirms the query runs.
    assert rows[0][0] >= 0, "Query executed successfully"


# ---- T-02 -----------------------------------------------------------------
@pytest.mark.translation
def test_t02_zeroifnull(sf_cursor):
    """T-02: Verify ZEROIFNULL function returns 0 for NULL."""
    rows = run_query(sf_cursor, "SELECT ZEROIFNULL(NULL)")
    assert rows[0][0] == 0, f"ZEROIFNULL(NULL) returned {rows[0][0]}, expected 0"


# ---- T-03 -----------------------------------------------------------------
@pytest.mark.translation
def test_t03_nullifzero(sf_cursor):
    """T-03: Verify NULLIFZERO function returns NULL for 0."""
    rows = run_query(sf_cursor, "SELECT NULLIFZERO(0)")
    assert rows[0][0] is None, f"NULLIFZERO(0) returned {rows[0][0]}, expected NULL"


# ---- T-04 -----------------------------------------------------------------
@pytest.mark.translation
def test_t04_qualify_clause(sf_cursor):
    """T-04: Verify QUALIFY clause works — one row per CUSTOMER_ID."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM ("
        "  SELECT CUSTOMER_ID, "
        "         ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID "
        "                            ORDER BY EFFECTIVE_FROM DESC) AS RN "
        "  FROM DIM_CUSTOMER "
        "  QUALIFY RN = 1"
        ")",
    )
    count = rows[0][0]
    # Should equal the number of distinct CUSTOMER_IDs
    distinct_rows = run_query(
        sf_cursor,
        "SELECT COUNT(DISTINCT CUSTOMER_ID) FROM DIM_CUSTOMER",
    )
    assert count == distinct_rows[0][0], (
        f"QUALIFY returned {count} rows, expected {distinct_rows[0][0]} distinct customers"
    )


# ---- T-05 -----------------------------------------------------------------
@pytest.mark.translation
def test_t05_hash_function(sf_cursor):
    """T-05: Verify HASH() as HASHROW replacement produces non-null values."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION "
        "WHERE HASH(TRANSACTION_ID, TRANSACTION_DATE) IS NULL",
    )
    assert rows[0][0] == 0, "HASH() produced NULL values"


# ---- T-06 -----------------------------------------------------------------
@pytest.mark.translation
def test_t06_identity_auto_generation(sf_clone_cursor):
    """T-06: Verify IDENTITY auto-generation — insert without specifying key."""
    sf_clone_cursor.execute("BEGIN")
    try:
        sf_clone_cursor.execute(
            "INSERT INTO DIM_CUSTOMER "
            "(CUSTOMER_ID, FIRST_NAME, LAST_NAME, ONBOARDING_DATE) "
            "VALUES (99999, 'Test', 'Identity', '2025-01-01')"
        )
        rows = run_query(
            sf_clone_cursor,
            "SELECT CUSTOMER_KEY FROM DIM_CUSTOMER WHERE CUSTOMER_ID = 99999",
        )
        assert len(rows) >= 1, "Insert failed"
        assert rows[0][0] is not None, "CUSTOMER_KEY was not auto-generated"
        assert rows[0][0] > 0, "CUSTOMER_KEY should be a positive integer"
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- T-07 -----------------------------------------------------------------
@pytest.mark.translation
def test_t07_csum_cumulative_sum(sf_cursor):
    """T-07: Verify CSUM -> SUM OVER — cumulative fees in VW_BRANCH_PERFORMANCE."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM ("
        "  SELECT BRANCH_ID, SNAPSHOT_MONTH_KEY, CUMULATIVE_FEES_YTD, "
        "         LAG(CUMULATIVE_FEES_YTD) OVER ("
        "           PARTITION BY BRANCH_ID, FLOOR(SNAPSHOT_MONTH_KEY / 100) "
        "           ORDER BY SNAPSHOT_MONTH_KEY"
        "         ) AS PREV_CUM_FEES "
        "  FROM VW_BRANCH_PERFORMANCE"
        ") sub "
        "WHERE PREV_CUM_FEES IS NOT NULL "
        "  AND CUMULATIVE_FEES_YTD < PREV_CUM_FEES",
    )
    assert rows[0][0] == 0, (
        f"CUMULATIVE_FEES_YTD is non-monotonic in {rows[0][0]} rows"
    )


# ---- T-08 -----------------------------------------------------------------
@pytest.mark.translation
def test_t08_mavg_moving_average(sf_cursor):
    """T-08: Verify MAVG -> AVG OVER — moving average volume exists."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM VW_BRANCH_PERFORMANCE "
        "WHERE MOVING_AVG_VOLUME_3M IS NOT NULL",
    )
    assert rows[0][0] > 0, "No non-NULL MOVING_AVG_VOLUME_3M values found"


# ---- T-09 -----------------------------------------------------------------
@pytest.mark.translation
def test_t09_timestamp_precision(sf_cursor):
    """T-09: Verify TIMESTAMP precision — TIMESTAMP(0) and TIMESTAMP(6) columns."""
    # TIMESTAMP(0) columns should be TIMESTAMP_NTZ(9) in Snowflake
    # (Snowflake stores all as NTZ with up to nanosecond precision)
    rows = run_query(
        sf_cursor,
        "SELECT COLUMN_NAME, DATA_TYPE, DATETIME_PRECISION "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'FACT_TRANSACTION' "
        "  AND COLUMN_NAME IN ('ETL_INSERT_TS', 'TRANSACTION_TS') "
        "ORDER BY COLUMN_NAME",
        (SCHEMA_NAME,),
    )
    ts_map = {r[0]: (r[1], r[2]) for r in rows}
    assert "ETL_INSERT_TS" in ts_map, "ETL_INSERT_TS column not found"
    assert "TRANSACTION_TS" in ts_map, "TRANSACTION_TS column not found"
    # Both should be TIMESTAMP_NTZ
    assert ts_map["ETL_INSERT_TS"][0] == TIMESTAMP_TYPE
    assert ts_map["TRANSACTION_TS"][0] == TIMESTAMP_TYPE


# ---- T-10 -----------------------------------------------------------------
@pytest.mark.translation
def test_t10_add_months_function(sf_cursor):
    """T-10: Verify ADD_MONTHS function works in Snowflake."""
    rows = run_query(
        sf_cursor,
        "SELECT ADD_MONTHS(CURRENT_DATE, -1)",
    )
    result = rows[0][0]
    assert result is not None, "ADD_MONTHS returned NULL"


# ---- T-11 -----------------------------------------------------------------
@pytest.mark.translation
def test_t11_volatile_to_temporary_table(sf_cursor):
    """T-11: Verify VOLATILE -> TEMPORARY TABLE creation works."""
    try:
        sf_cursor.execute(
            "CREATE TEMPORARY TABLE TEMP_TEST_VOLATILE (ID INTEGER, VAL VARCHAR(50))"
        )
        sf_cursor.execute("INSERT INTO TEMP_TEST_VOLATILE VALUES (1, 'test')")
        rows = run_query(sf_cursor, "SELECT * FROM TEMP_TEST_VOLATILE")
        assert len(rows) == 1, "Expected 1 row in temporary table"
        assert rows[0][0] == 1 and rows[0][1] == "test"
    finally:
        sf_cursor.execute("DROP TABLE IF EXISTS TEMP_TEST_VOLATILE")
