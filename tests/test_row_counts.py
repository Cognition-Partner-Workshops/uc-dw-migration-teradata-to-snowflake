"""
Category 2: Row Count Validation (Positive Tests)
Test IDs: R-01 through R-09

Verifies that the Snowflake target contains the expected number of rows
per table, per partition, and per distinct key.
"""

import pytest

from tests.config import (
    APPROXIMATE_COUNT_TABLES,
    EXPECTED_ROW_COUNTS,
    ROW_COUNT_TOLERANCE,
    SCHEMA_NAME,
    TABLES,
)
from tests.utils import assert_row_count, run_query


# ---- R-01 through R-07 ---------------------------------------------------
@pytest.mark.row_count
@pytest.mark.parametrize("table_name", TABLES)
def test_r01_to_r07_table_row_counts(sf_cursor, table_name):
    """R-01..R-07: Verify row count for each table."""
    expected = EXPECTED_ROW_COUNTS[table_name]
    tolerance = ROW_COUNT_TOLERANCE if table_name in APPROXIMATE_COUNT_TABLES else 0.0
    assert_row_count(sf_cursor, table_name, expected, tolerance=tolerance)


# ---- R-08 -----------------------------------------------------------------
@pytest.mark.row_count
def test_r08_fact_transaction_partition_counts(sf_cursor):
    """R-08: Verify row counts per partition (FACT_TRANSACTION by year-month)."""
    rows = run_query(
        sf_cursor,
        "SELECT EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR, "
        "       EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH, "
        "       COUNT(*) AS ROW_COUNT "
        "FROM FACT_TRANSACTION "
        "GROUP BY 1, 2 "
        "ORDER BY 1, 2",
    )
    # Every partition should have at least 1 row
    assert len(rows) > 0, "No partition data found in FACT_TRANSACTION"
    for year, month, count in rows:
        assert count > 0, (
            f"FACT_TRANSACTION partition {int(year)}-{int(month):02d} has 0 rows"
        )

    # Total across partitions should match overall count
    total = sum(r[2] for r in rows)
    expected = EXPECTED_ROW_COUNTS["FACT_TRANSACTION"]
    tolerance = ROW_COUNT_TOLERANCE
    lower = expected * (1 - tolerance)
    upper = expected * (1 + tolerance)
    assert lower <= total <= upper, (
        f"Partition total {total} outside tolerance of {expected} ±{tolerance*100:.0f}%"
    )


# ---- R-09 -----------------------------------------------------------------
@pytest.mark.row_count
@pytest.mark.parametrize(
    "table_name,key_column",
    [
        ("DIM_CUSTOMER", "CUSTOMER_KEY"),
        ("DIM_ACCOUNT", "ACCOUNT_KEY"),
        ("DIM_PRODUCT", "PRODUCT_ID"),
        ("DIM_BRANCH", "BRANCH_ID"),
        ("DIM_DATE", "DATE_KEY"),
        ("FACT_TRANSACTION", "TRANSACTION_ID"),
    ],
)
def test_r09_distinct_key_counts(sf_cursor, table_name, key_column):
    """R-09: Verify distinct key counts per table."""
    rows = run_query(
        sf_cursor,
        f"SELECT COUNT(DISTINCT {key_column}) FROM {table_name}",
    )
    distinct_count = rows[0][0]
    assert distinct_count > 0, (
        f"{table_name}.{key_column}: distinct count is 0"
    )
    # For dimension tables the distinct count should be >= expected row count
    # (SCD2 tables may have more rows than distinct natural keys)
    if table_name.startswith("DIM_"):
        expected = EXPECTED_ROW_COUNTS.get(table_name)
        if expected and table_name not in ("DIM_CUSTOMER", "DIM_ACCOUNT"):
            # Non-SCD tables: distinct keys == row count
            assert distinct_count == expected, (
                f"{table_name}: expected {expected} distinct keys, got {distinct_count}"
            )
