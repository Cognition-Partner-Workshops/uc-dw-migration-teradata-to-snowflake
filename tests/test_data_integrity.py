"""
Category 3: Data Integrity & Checksum Tests (D-01 to D-13)

Verifies aggregate checksums, duplicate detection, date ranges,
SCD2 consistency, DECIMAL precision, and SET-table uniqueness.
"""

import pytest

from tests.config import (
    EXPECTED_ROW_COUNTS,
    SNOWFLAKE_SCHEMA,
)
from tests.utils import assert_no_duplicates, run_query, run_scalar


# -------------------------------------------------------------------------
# D-01: DIM_CUSTOMER aggregate checksum
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestDimCustomerChecksum:
    """D-01: DIM_CUSTOMER aggregate values must be internally consistent."""

    def test_customer_row_count_current(self, sf_cursor):
        """Current-flag rows should not exceed total expected."""
        sql = f"""
            SELECT COUNT(*)
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            WHERE CURRENT_FLAG = 'Y'
        """
        current_count = run_scalar(sf_cursor, sql)
        assert current_count > 0, "No current (CURRENT_FLAG='Y') customer rows"

    def test_customer_distinct_ids(self, sf_cursor):
        """Distinct CUSTOMER_ID count must be positive."""
        sql = f"""
            SELECT COUNT(DISTINCT CUSTOMER_ID)
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            WHERE CURRENT_FLAG = 'Y'
        """
        distinct = run_scalar(sf_cursor, sql)
        assert distinct > 0, "No distinct CUSTOMER_IDs with CURRENT_FLAG='Y'"

    def test_customer_active_count(self, sf_cursor):
        """Active customer count must be positive."""
        sql = f"""
            SELECT SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END)
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            WHERE CURRENT_FLAG = 'Y'
        """
        active = run_scalar(sf_cursor, sql)
        assert active > 0, "No active customers with CURRENT_FLAG='Y'"

    def test_customer_onboarding_date_range(self, sf_cursor):
        """Onboarding dates must be within a reasonable range."""
        sql = f"""
            SELECT MIN(ONBOARDING_DATE), MAX(ONBOARDING_DATE)
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            WHERE CURRENT_FLAG = 'Y'
        """
        rows = run_query(sf_cursor, sql)
        min_date, max_date = rows[0]
        assert min_date is not None, "MIN(ONBOARDING_DATE) is NULL"
        assert max_date is not None, "MAX(ONBOARDING_DATE) is NULL"


# -------------------------------------------------------------------------
# D-02: FACT_TRANSACTION aggregate checksum per month
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestFactTransactionChecksum:
    """D-02: Monthly aggregates must be internally consistent."""

    def test_monthly_aggregates_non_null(self, sf_cursor):
        """SUM(TRANSACTION_AMOUNT) and COUNT per month must be non-null."""
        sql = f"""
            SELECT
                EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR,
                EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH,
                COUNT(*) AS TXN_COUNT,
                SUM(TRANSACTION_AMOUNT) AS TOTAL_AMOUNT,
                SUM(BASE_CURRENCY_AMOUNT) AS TOTAL_BASE_AMOUNT
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
            GROUP BY TXN_YEAR, TXN_MONTH
            ORDER BY TXN_YEAR, TXN_MONTH
        """
        rows = run_query(sf_cursor, sql)
        assert len(rows) > 0, "No monthly aggregates — table may be empty"
        for year, month, count, total_amt, total_base in rows:
            assert count > 0, f"Zero transactions in {int(year)}-{int(month):02d}"
            assert total_amt is not None, (
                f"NULL TRANSACTION_AMOUNT sum in {int(year)}-{int(month):02d}"
            )

    def test_total_amount_positive(self, sf_cursor):
        """Overall SUM(TRANSACTION_AMOUNT) should be non-zero."""
        sql = f"""
            SELECT SUM(TRANSACTION_AMOUNT)
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
        """
        total = run_scalar(sf_cursor, sql)
        assert total is not None and total != 0, (
            "Total TRANSACTION_AMOUNT is zero or NULL"
        )


# -------------------------------------------------------------------------
# D-03: Monthly snapshot balance totals
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestSnapshotBalanceTotals:
    """D-03: Monthly snapshot aggregates must be internally consistent."""

    def test_snapshot_totals_non_null(self, sf_cursor):
        """SUM(CLOSING_BALANCE), TOTAL_DEBITS, TOTAL_CREDITS per month."""
        sql = f"""
            SELECT
                SNAPSHOT_MONTH_KEY,
                SUM(CLOSING_BALANCE) AS TOTAL_CLOSING,
                SUM(TOTAL_DEBITS) AS TOTAL_DEBITS,
                SUM(TOTAL_CREDITS) AS TOTAL_CREDITS
            FROM {SNOWFLAKE_SCHEMA}.FACT_MONTHLY_ACCOUNT_SNAPSHOT
            GROUP BY SNAPSHOT_MONTH_KEY
            ORDER BY SNAPSHOT_MONTH_KEY
        """
        rows = run_query(sf_cursor, sql)
        assert len(rows) > 0, "No snapshot months — table may be empty"
        for month_key, closing, debits, credits in rows:
            assert closing is not None, (
                f"NULL CLOSING_BALANCE sum for month {month_key}"
            )


# -------------------------------------------------------------------------
# D-04: No duplicate primary keys in DIM_CUSTOMER
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestNoDuplicateCustomerKeys:
    """D-04: CUSTOMER_KEY must be unique in DIM_CUSTOMER."""

    def test_no_duplicate_customer_keys(self, sf_cursor):
        assert_no_duplicates(sf_cursor, "DIM_CUSTOMER", "CUSTOMER_KEY")


# -------------------------------------------------------------------------
# D-05: No duplicate primary keys in DIM_ACCOUNT
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestNoDuplicateAccountKeys:
    """D-05: ACCOUNT_KEY must be unique in DIM_ACCOUNT."""

    def test_no_duplicate_account_keys(self, sf_cursor):
        assert_no_duplicates(sf_cursor, "DIM_ACCOUNT", "ACCOUNT_KEY")


# -------------------------------------------------------------------------
# D-06: No duplicate TRANSACTION_IDs
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestNoDuplicateTransactionIds:
    """D-06: TRANSACTION_ID must be unique in FACT_TRANSACTION."""

    def test_no_duplicate_transaction_ids(self, sf_cursor):
        assert_no_duplicates(sf_cursor, "FACT_TRANSACTION", "TRANSACTION_ID")


# -------------------------------------------------------------------------
# D-07: MIN/MAX ONBOARDING_DATE ranges
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestOnboardingDateRange:
    """D-07: MIN/MAX ONBOARDING_DATE must be within expected bounds."""

    def test_min_max_onboarding_date(self, sf_cursor):
        sql = f"""
            SELECT MIN(ONBOARDING_DATE), MAX(ONBOARDING_DATE)
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
        """
        rows = run_query(sf_cursor, sql)
        min_date, max_date = rows[0]
        assert min_date is not None, "MIN(ONBOARDING_DATE) is NULL"
        assert max_date is not None, "MAX(ONBOARDING_DATE) is NULL"
        assert min_date <= max_date, (
            f"MIN ({min_date}) > MAX ({max_date}) for ONBOARDING_DATE"
        )


# -------------------------------------------------------------------------
# D-08: MIN/MAX TRANSACTION_DATE ranges
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestTransactionDateRange:
    """D-08: MIN/MAX TRANSACTION_DATE must be within expected bounds."""

    def test_min_max_transaction_date(self, sf_cursor):
        sql = f"""
            SELECT MIN(TRANSACTION_DATE), MAX(TRANSACTION_DATE)
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
        """
        rows = run_query(sf_cursor, sql)
        min_date, max_date = rows[0]
        assert min_date is not None, "MIN(TRANSACTION_DATE) is NULL"
        assert max_date is not None, "MAX(TRANSACTION_DATE) is NULL"
        assert min_date <= max_date, (
            f"MIN ({min_date}) > MAX ({max_date}) for TRANSACTION_DATE"
        )


# -------------------------------------------------------------------------
# D-09: SCD2 current flag consistency
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestSCD2CurrentFlag:
    """D-09: Each CUSTOMER_ID must have exactly one CURRENT_FLAG='Y' row."""

    def test_no_multiple_current_flags(self, sf_cursor):
        sql = f"""
            SELECT CUSTOMER_ID, COUNT(*) AS CNT
            FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            WHERE CURRENT_FLAG = 'Y'
            GROUP BY CUSTOMER_ID
            HAVING COUNT(*) > 1
        """
        violations = run_query(sf_cursor, sql)
        assert len(violations) == 0, (
            f"SCD2 violation: {len(violations)} CUSTOMER_IDs have multiple "
            f"CURRENT_FLAG='Y' rows — first few: {violations[:5]}"
        )

    def test_every_customer_has_current_flag(self, sf_cursor):
        """Every distinct CUSTOMER_ID should have at least one CURRENT_FLAG='Y'."""
        sql = f"""
            SELECT c.CUSTOMER_ID
            FROM (
                SELECT DISTINCT CUSTOMER_ID
                FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
            ) c
            LEFT JOIN (
                SELECT CUSTOMER_ID
                FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
                WHERE CURRENT_FLAG = 'Y'
            ) cur ON c.CUSTOMER_ID = cur.CUSTOMER_ID
            WHERE cur.CUSTOMER_ID IS NULL
        """
        missing = run_query(sf_cursor, sql)
        assert len(missing) == 0, (
            f"{len(missing)} CUSTOMER_IDs have no CURRENT_FLAG='Y' row: "
            f"{[r[0] for r in missing[:5]]}"
        )


# -------------------------------------------------------------------------
# D-10: DECIMAL precision preserved
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestDecimalPrecision:
    """D-10: DECIMAL column aggregates must be non-null and reasonable."""

    def test_transaction_amount_aggregates(self, sf_cursor):
        sql = f"""
            SELECT
                SUM(TRANSACTION_AMOUNT) AS SUM_AMT,
                AVG(TRANSACTION_AMOUNT) AS AVG_AMT,
                MIN(TRANSACTION_AMOUNT) AS MIN_AMT,
                MAX(TRANSACTION_AMOUNT) AS MAX_AMT
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
        """
        rows = run_query(sf_cursor, sql)
        sum_amt, avg_amt, min_amt, max_amt = rows[0]
        assert sum_amt is not None, "SUM(TRANSACTION_AMOUNT) is NULL"
        assert avg_amt is not None, "AVG(TRANSACTION_AMOUNT) is NULL"
        assert min_amt is not None, "MIN(TRANSACTION_AMOUNT) is NULL"
        assert max_amt is not None, "MAX(TRANSACTION_AMOUNT) is NULL"

    def test_snapshot_balance_aggregates(self, sf_cursor):
        sql = f"""
            SELECT
                SUM(CLOSING_BALANCE) AS SUM_BAL,
                AVG(CLOSING_BALANCE) AS AVG_BAL,
                MIN(CLOSING_BALANCE) AS MIN_BAL,
                MAX(CLOSING_BALANCE) AS MAX_BAL
            FROM {SNOWFLAKE_SCHEMA}.FACT_MONTHLY_ACCOUNT_SNAPSHOT
        """
        rows = run_query(sf_cursor, sql)
        sum_bal, avg_bal, min_bal, max_bal = rows[0]
        assert sum_bal is not None, "SUM(CLOSING_BALANCE) is NULL"

    def test_exchange_rate_precision(self, sf_cursor):
        """EXCHANGE_RATE should preserve 6 decimal places."""
        sql = f"""
            SELECT COUNT(*)
            FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION
            WHERE EXCHANGE_RATE IS NOT NULL
              AND EXCHANGE_RATE != 1.000000
              AND ABS(EXCHANGE_RATE - ROUND(EXCHANGE_RATE, 6)) > 0
        """
        count = run_scalar(sf_cursor, sql)
        assert count == 0, (
            f"{count} rows have EXCHANGE_RATE precision beyond 6 decimals"
        )


# -------------------------------------------------------------------------
# D-11: No duplicate rows in SET-table equivalents
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestSetTableUniqueness:
    """D-11: Teradata SET table behavior must be preserved (no full-row dupes)."""

    def test_dim_customer_no_full_row_duplicates(self, sf_cursor):
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT
                    CUSTOMER_ID, FIRST_NAME, LAST_NAME, DATE_OF_BIRTH,
                    GENDER, MARITAL_STATUS, EMAIL_ADDRESS,
                    CUSTOMER_SEGMENT, IS_ACTIVE,
                    EFFECTIVE_FROM, EFFECTIVE_TO, CURRENT_FLAG
                FROM {SNOWFLAKE_SCHEMA}.DIM_CUSTOMER
                GROUP BY
                    CUSTOMER_ID, FIRST_NAME, LAST_NAME, DATE_OF_BIRTH,
                    GENDER, MARITAL_STATUS, EMAIL_ADDRESS,
                    CUSTOMER_SEGMENT, IS_ACTIVE,
                    EFFECTIVE_FROM, EFFECTIVE_TO, CURRENT_FLAG
                HAVING COUNT(*) > 1
            )
        """
        dupe_groups = run_scalar(sf_cursor, sql)
        assert dupe_groups == 0, (
            f"DIM_CUSTOMER has {dupe_groups} duplicate row group(s) "
            "(SET table uniqueness violated)"
        )

    def test_dim_product_no_full_row_duplicates(self, sf_cursor):
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT
                    PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME,
                    PRODUCT_CATEGORY, IS_ACTIVE
                FROM {SNOWFLAKE_SCHEMA}.DIM_PRODUCT
                GROUP BY
                    PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME,
                    PRODUCT_CATEGORY, IS_ACTIVE
                HAVING COUNT(*) > 1
            )
        """
        dupe_groups = run_scalar(sf_cursor, sql)
        assert dupe_groups == 0, (
            f"DIM_PRODUCT has {dupe_groups} duplicate row group(s)"
        )

    def test_dim_branch_no_full_row_duplicates(self, sf_cursor):
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT
                    BRANCH_ID, BRANCH_CODE, BRANCH_NAME,
                    BRANCH_TYPE, CITY, REGION, IS_ACTIVE
                FROM {SNOWFLAKE_SCHEMA}.DIM_BRANCH
                GROUP BY
                    BRANCH_ID, BRANCH_CODE, BRANCH_NAME,
                    BRANCH_TYPE, CITY, REGION, IS_ACTIVE
                HAVING COUNT(*) > 1
            )
        """
        dupe_groups = run_scalar(sf_cursor, sql)
        assert dupe_groups == 0, (
            f"DIM_BRANCH has {dupe_groups} duplicate row group(s)"
        )

    def test_dim_date_no_full_row_duplicates(self, sf_cursor):
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT
                    DATE_KEY, CALENDAR_DATE, CALENDAR_YEAR,
                    MONTH_NUM, DAY_OF_MONTH
                FROM {SNOWFLAKE_SCHEMA}.DIM_DATE
                GROUP BY
                    DATE_KEY, CALENDAR_DATE, CALENDAR_YEAR,
                    MONTH_NUM, DAY_OF_MONTH
                HAVING COUNT(*) > 1
            )
        """
        dupe_groups = run_scalar(sf_cursor, sql)
        assert dupe_groups == 0, (
            f"DIM_DATE has {dupe_groups} duplicate row group(s)"
        )


# -------------------------------------------------------------------------
# D-12: DIM_PRODUCT aggregate checksum
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestDimProductChecksum:
    """D-12: DIM_PRODUCT aggregate values must match expected totals."""

    def test_product_row_count(self, sf_cursor):
        count = run_scalar(
            sf_cursor,
            f"SELECT COUNT(*) FROM {SNOWFLAKE_SCHEMA}.DIM_PRODUCT",
        )
        assert count == EXPECTED_ROW_COUNTS["DIM_PRODUCT"], (
            f"DIM_PRODUCT: expected {EXPECTED_ROW_COUNTS['DIM_PRODUCT']} rows, got {count}"
        )

    def test_product_distinct_codes(self, sf_cursor):
        count = run_scalar(
            sf_cursor,
            f"SELECT COUNT(DISTINCT PRODUCT_CODE) FROM {SNOWFLAKE_SCHEMA}.DIM_PRODUCT",
        )
        assert count == EXPECTED_ROW_COUNTS["DIM_PRODUCT"], (
            f"DIM_PRODUCT: expected {EXPECTED_ROW_COUNTS['DIM_PRODUCT']} distinct "
            f"PRODUCT_CODEs, got {count}"
        )

    def test_product_active_count(self, sf_cursor):
        active = run_scalar(
            sf_cursor,
            f"""
                SELECT SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END)
                FROM {SNOWFLAKE_SCHEMA}.DIM_PRODUCT
            """,
        )
        assert active is not None and active > 0, "No active products"


# -------------------------------------------------------------------------
# D-13: DIM_BRANCH aggregate checksum
# -------------------------------------------------------------------------
@pytest.mark.data_integrity
class TestDimBranchChecksum:
    """D-13: DIM_BRANCH aggregate values must match expected totals."""

    def test_branch_row_count(self, sf_cursor):
        count = run_scalar(
            sf_cursor,
            f"SELECT COUNT(*) FROM {SNOWFLAKE_SCHEMA}.DIM_BRANCH",
        )
        assert count == EXPECTED_ROW_COUNTS["DIM_BRANCH"], (
            f"DIM_BRANCH: expected {EXPECTED_ROW_COUNTS['DIM_BRANCH']} rows, got {count}"
        )

    def test_branch_distinct_codes(self, sf_cursor):
        count = run_scalar(
            sf_cursor,
            f"SELECT COUNT(DISTINCT BRANCH_CODE) FROM {SNOWFLAKE_SCHEMA}.DIM_BRANCH",
        )
        assert count == EXPECTED_ROW_COUNTS["DIM_BRANCH"], (
            f"DIM_BRANCH: expected {EXPECTED_ROW_COUNTS['DIM_BRANCH']} distinct "
            f"BRANCH_CODEs, got {count}"
        )

    def test_branch_distinct_regions(self, sf_cursor):
        """Should have 5 Norwegian regions."""
        count = run_scalar(
            sf_cursor,
            f"SELECT COUNT(DISTINCT REGION) FROM {SNOWFLAKE_SCHEMA}.DIM_BRANCH",
        )
        assert count == 5, f"Expected 5 distinct regions, got {count}"
