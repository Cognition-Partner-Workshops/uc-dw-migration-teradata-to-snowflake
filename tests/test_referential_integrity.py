"""
Category 4: Referential Integrity Tests (RI-01 to RI-10)

Verifies that foreign-key relationships between fact and dimension tables
are intact after migration — no orphaned records.
"""

import pytest

from tests.config import SNOWFLAKE_SCHEMA
from tests.utils import assert_no_orphans, run_scalar


# -------------------------------------------------------------------------
# RI-01: No orphan transactions (ACCOUNT_KEY)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanTransactionAccountKey:
    """RI-01: Every FACT_TRANSACTION.ACCOUNT_KEY must exist in DIM_ACCOUNT."""

    def test_no_orphan_transaction_account_key(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_TRANSACTION",
            child_column="ACCOUNT_KEY",
            parent_table="DIM_ACCOUNT",
            parent_column="ACCOUNT_KEY",
        )


# -------------------------------------------------------------------------
# RI-02: No orphan transactions (CUSTOMER_KEY)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanTransactionCustomerKey:
    """RI-02: Every FACT_TRANSACTION.CUSTOMER_KEY must exist in DIM_CUSTOMER."""

    def test_no_orphan_transaction_customer_key(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_TRANSACTION",
            child_column="CUSTOMER_KEY",
            parent_table="DIM_CUSTOMER",
            parent_column="CUSTOMER_KEY",
        )


# -------------------------------------------------------------------------
# RI-03: No orphan snapshots (ACCOUNT_KEY)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanSnapshotAccountKey:
    """RI-03: Every snapshot ACCOUNT_KEY must exist in DIM_ACCOUNT."""

    def test_no_orphan_snapshot_account_key(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_MONTHLY_ACCOUNT_SNAPSHOT",
            child_column="ACCOUNT_KEY",
            parent_table="DIM_ACCOUNT",
            parent_column="ACCOUNT_KEY",
        )


# -------------------------------------------------------------------------
# RI-04: No orphan accounts (CUSTOMER_ID)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanAccountCustomerId:
    """RI-04: Every DIM_ACCOUNT.CUSTOMER_ID must exist in DIM_CUSTOMER."""

    def test_no_orphan_account_customer_id(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="DIM_ACCOUNT",
            child_column="CUSTOMER_ID",
            parent_table="DIM_CUSTOMER",
            parent_column="CUSTOMER_ID",
        )


# -------------------------------------------------------------------------
# RI-05: No orphan accounts (BRANCH_ID)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanAccountBranchId:
    """RI-05: Every non-NULL DIM_ACCOUNT.BRANCH_ID must exist in DIM_BRANCH."""

    def test_no_orphan_account_branch_id(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="DIM_ACCOUNT",
            child_column="BRANCH_ID",
            parent_table="DIM_BRANCH",
            parent_column="BRANCH_ID",
            allow_null=True,
        )


# -------------------------------------------------------------------------
# RI-06: No orphan accounts (PRODUCT_ID)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanAccountProductId:
    """RI-06: Every DIM_ACCOUNT.PRODUCT_ID must exist in DIM_PRODUCT."""

    def test_no_orphan_account_product_id(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="DIM_ACCOUNT",
            child_column="PRODUCT_ID",
            parent_table="DIM_PRODUCT",
            parent_column="PRODUCT_ID",
        )


# -------------------------------------------------------------------------
# RI-07: FACT_TRANSACTION.DATE_KEY references DIM_DATE
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanTransactionDateKey:
    """RI-07: Every FACT_TRANSACTION.DATE_KEY must exist in DIM_DATE."""

    def test_no_orphan_transaction_date_key(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_TRANSACTION",
            child_column="DATE_KEY",
            parent_table="DIM_DATE",
            parent_column="DATE_KEY",
        )


# -------------------------------------------------------------------------
# RI-08: FACT_TRANSACTION.PRODUCT_ID references DIM_PRODUCT
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanTransactionProductId:
    """RI-08: Every FACT_TRANSACTION.PRODUCT_ID must exist in DIM_PRODUCT."""

    def test_no_orphan_transaction_product_id(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_TRANSACTION",
            child_column="PRODUCT_ID",
            parent_table="DIM_PRODUCT",
            parent_column="PRODUCT_ID",
        )


# -------------------------------------------------------------------------
# RI-09: Detect orphans when dimension record is missing (negative test)
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestOrphanDetectionNegative:
    """RI-09: Insert a fact row with a non-existent ACCOUNT_KEY and verify detection.

    This test uses a transaction/rollback pattern to avoid permanent changes.
    It should be run in a cloned schema for full isolation.
    """

    def test_orphan_detection_with_rollback(self, sf_cursor, sf_connection):
        """Insert an orphan row, detect it, then rollback."""
        # Use a non-existent ACCOUNT_KEY that is very unlikely to exist
        fake_account_key = 9999999999

        # Verify this key does not already exist
        exists = run_scalar(
            sf_cursor,
            f"""
                SELECT COUNT(*)
                FROM {SNOWFLAKE_SCHEMA}.DIM_ACCOUNT
                WHERE ACCOUNT_KEY = %s
            """,
            (fake_account_key,),
        )
        assert exists == 0, (
            f"ACCOUNT_KEY {fake_account_key} unexpectedly exists in DIM_ACCOUNT"
        )

        try:
            sf_cursor.execute("BEGIN")

            # Insert an orphan transaction row
            sf_cursor.execute(f"""
                INSERT INTO {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION (
                    TRANSACTION_ID, TRANSACTION_DATE, ACCOUNT_KEY,
                    CUSTOMER_KEY, PRODUCT_ID, DATE_KEY,
                    TRANSACTION_TYPE, TRANSACTION_AMOUNT
                ) VALUES (
                    -99999, '2025-01-01', {fake_account_key},
                    1, 1, 20250101,
                    'DEBIT', 100.00
                )
            """)

            # Verify orphan is detected
            orphan_count = run_scalar(
                sf_cursor,
                f"""
                    SELECT COUNT(*)
                    FROM {SNOWFLAKE_SCHEMA}.FACT_TRANSACTION ft
                    WHERE ft.ACCOUNT_KEY NOT IN (
                        SELECT ACCOUNT_KEY FROM {SNOWFLAKE_SCHEMA}.DIM_ACCOUNT
                    )
                """,
            )
            assert orphan_count >= 1, (
                "Orphan detection failed: expected at least 1 orphan after "
                "inserting a row with a non-existent ACCOUNT_KEY"
            )

        finally:
            sf_cursor.execute("ROLLBACK")


# -------------------------------------------------------------------------
# RI-10: Snapshot CUSTOMER_KEY references DIM_CUSTOMER
# -------------------------------------------------------------------------
@pytest.mark.referential_integrity
class TestNoOrphanSnapshotCustomerKey:
    """RI-10: Every snapshot CUSTOMER_KEY must exist in DIM_CUSTOMER."""

    def test_no_orphan_snapshot_customer_key(self, sf_cursor):
        assert_no_orphans(
            sf_cursor,
            child_table="FACT_MONTHLY_ACCOUNT_SNAPSHOT",
            child_column="CUSTOMER_KEY",
            parent_table="DIM_CUSTOMER",
            parent_column="CUSTOMER_KEY",
        )
