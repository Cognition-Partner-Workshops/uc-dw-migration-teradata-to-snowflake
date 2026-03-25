"""
Category 2: Row Count Validation Tests (R-01 to R-09)

Verifies that row counts in the Snowflake target match expected values
from the Teradata source (exact for dimensions, ±5% for fact tables).
"""

import pytest

from tests.config import (
    APPROXIMATE_COUNT_TABLES,
    EXPECTED_ROW_COUNTS,
    PRIMARY_KEY_COLUMNS,
    ROW_COUNT_TOLERANCE_PCT,
    SNOWFLAKE_SCHEMA,
)
from tests.utils import assert_row_count, run_query, run_scalar


# -------------------------------------------------------------------------
# R-01 to R-07: Verify row counts per table
# -------------------------------------------------------------------------
@pytest.mark.row_count
class TestTableRowCounts:
    """R-01 to R-07: Row counts per table must match expected values."""

    @pytest.mark.parametrize(
        "table_name,expected_count",
        [
            (t, c)
            for t, c in EXPECTED_ROW_COUNTS.items()
            if t not in APPROXIMATE_COUNT_TABLES
        ],
        ids=[
            t for t in EXPECTED_ROW_COUNTS if t not in APPROXIMATE_COUNT_TABLES
        ],
    )
    def test_exact_row_count(self, sf_cursor, table_name, expected_count):
        """Dimension tables must have exact row counts."""
        assert_row_count(sf_cursor, table_name, expected_count, tolerance_pct=0.0)

    @pytest.mark.parametrize(
        "table_name,expected_count",
        [
            (t, c)
            for t, c in EXPECTED_ROW_COUNTS.items()
            if t in APPROXIMATE_COUNT_TABLES
        ],
        ids=[t for t in EXPECTED_ROW_COUNTS if t in APPROXIMATE_COUNT_TABLES],
    )
    def test_approximate_row_count(self, sf_cursor, table_name, expected_count):
        """Fact tables use approximate matching (±5% tolerance)."""
        assert_row_count(
            sf_cursor,
            table_name,
            expected_count,
            tolerance_pct=ROW_COUNT_TOLERANCE_PCT,
        )


# -------------------------------------------------------------------------
# R-08: Verify row counts per partition (FACT_TRANSACTION by year-month)
# -------------------------------------------------------------------------
@pytest.mark.row_count
class TestPartitionRowCounts:
    """R-08: FACT_TRANSACTION row counts per year-month partition."""

    def test_partition_counts_non_empty(self, sf_cursor):
        """Every year-month partition must contain at least one row."""
        sql = f"""
            SELECT
                EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR,
                EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH,
                COUNT(*) AS ROW_COUNT
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
            GROUP BY TXN_YEAR, TXN_MONTH
            ORDER BY TXN_YEAR, TXN_MONTH
        """
        rows = run_query(sf_cursor, sql)
        assert len(rows) > 0, "FACT_TRANSACTION has no partitions (empty table)"
        for year, month, count in rows:
            assert count > 0, (
                f"Partition {int(year)}-{int(month):02d} has zero rows"
            )

    def test_partition_count_sum_equals_total(self, sf_cursor):
        """Sum of partition row counts must equal total table count."""
        sql_partitions = f"""
            SELECT SUM(cnt) FROM (
                SELECT COUNT(*) AS cnt
                FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
                GROUP BY EXTRACT(YEAR FROM TRANSACTION_DATE),
                         EXTRACT(MONTH FROM TRANSACTION_DATE)
            )
        """
        partition_sum = run_scalar(sf_cursor, sql_partitions)
        total = run_scalar(
            sf_cursor,
            f"SELECT COUNT(*) FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION",
        )
        assert partition_sum == total, (
            f"Partition sum ({partition_sum}) != total count ({total})"
        )


# -------------------------------------------------------------------------
# R-09: Verify distinct key counts per table
# -------------------------------------------------------------------------
@pytest.mark.row_count
class TestDistinctKeyCounts:
    """R-09: Distinct key counts per table must be positive and consistent."""

    @pytest.mark.parametrize(
        "table_name,key_column",
        list(PRIMARY_KEY_COLUMNS.items()),
        ids=list(PRIMARY_KEY_COLUMNS.keys()),
    )
    def test_distinct_key_count_positive(self, sf_cursor, table_name, key_column):
        """Each table must have at least one distinct key value."""
        sql = f"""
            SELECT COUNT(DISTINCT {key_column})
            FROM {SNOWFLAKE_SCHEMA}.{table_name}
        """
        distinct_count = run_scalar(sf_cursor, sql)
        assert distinct_count > 0, (
            f"{table_name}: no distinct {key_column} values found"
        )

    @pytest.mark.parametrize(
        "table_name,key_column",
        [
            (t, k) for t, k in PRIMARY_KEY_COLUMNS.items()
            if t not in ("FACT_TRANSACTION",)
        ],
        ids=[
            t for t in PRIMARY_KEY_COLUMNS
            if t not in ("FACT_TRANSACTION",)
        ],
    )
    def test_distinct_key_equals_row_count(self, sf_cursor, table_name, key_column):
        """For tables with unique keys, distinct count must equal row count."""
        total = run_scalar(
            sf_cursor,
            f"SELECT COUNT(*) FROM {SNOWFLAKE_SCHEMA}.{table_name}",
        )
        distinct = run_scalar(
            sf_cursor,
            f"SELECT COUNT(DISTINCT {key_column}) FROM {SNOWFLAKE_SCHEMA}.{table_name}",
        )
        assert distinct == total, (
            f"{table_name}: distinct {key_column} count ({distinct}) != "
            f"total rows ({total}) — possible duplicates"
        )
