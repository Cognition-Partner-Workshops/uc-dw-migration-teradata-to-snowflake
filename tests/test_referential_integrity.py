"""
Category 4: Referential Integrity Tests (Positive & Negative)
Test IDs: RI-01 through RI-10

Verifies that foreign-key relationships between fact and dimension tables
are intact — no orphaned records after migration.
"""

import pytest

from tests.utils import run_query


# ---- RI-01 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri01_no_orphan_transactions_account_key(sf_cursor):
    """RI-01: No orphan transactions (ACCOUNT_KEY)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION ft "
        "WHERE ft.ACCOUNT_KEY NOT IN (SELECT ACCOUNT_KEY FROM DIM_ACCOUNT)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan transactions by ACCOUNT_KEY"


# ---- RI-02 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri02_no_orphan_transactions_customer_key(sf_cursor):
    """RI-02: No orphan transactions (CUSTOMER_KEY)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION ft "
        "WHERE ft.CUSTOMER_KEY NOT IN (SELECT CUSTOMER_KEY FROM DIM_CUSTOMER)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan transactions by CUSTOMER_KEY"


# ---- RI-03 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri03_no_orphan_snapshots_account_key(sf_cursor):
    """RI-03: No orphan snapshots (ACCOUNT_KEY)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT snap "
        "WHERE snap.ACCOUNT_KEY NOT IN (SELECT ACCOUNT_KEY FROM DIM_ACCOUNT)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan snapshots by ACCOUNT_KEY"


# ---- RI-04 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri04_no_orphan_accounts_customer_id(sf_cursor):
    """RI-04: No orphan accounts (CUSTOMER_ID)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_ACCOUNT a "
        "WHERE a.CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM DIM_CUSTOMER)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan accounts by CUSTOMER_ID"


# ---- RI-05 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri05_no_orphan_accounts_branch_id(sf_cursor):
    """RI-05: No orphan accounts (BRANCH_ID)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_ACCOUNT a "
        "WHERE a.BRANCH_ID IS NOT NULL "
        "  AND a.BRANCH_ID NOT IN (SELECT BRANCH_ID FROM DIM_BRANCH)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan accounts by BRANCH_ID"


# ---- RI-06 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri06_no_orphan_accounts_product_id(sf_cursor):
    """RI-06: No orphan accounts (PRODUCT_ID)."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_ACCOUNT a "
        "WHERE a.PRODUCT_ID NOT IN (SELECT PRODUCT_ID FROM DIM_PRODUCT)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan accounts by PRODUCT_ID"


# ---- RI-07 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri07_fact_transaction_date_key_references_dim_date(sf_cursor):
    """RI-07: FACT_TRANSACTION.DATE_KEY references DIM_DATE."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION ft "
        "WHERE ft.DATE_KEY NOT IN (SELECT DATE_KEY FROM DIM_DATE)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan transactions by DATE_KEY"


# ---- RI-08 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri08_fact_transaction_product_id_references_dim_product(sf_cursor):
    """RI-08: FACT_TRANSACTION.PRODUCT_ID references DIM_PRODUCT."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_TRANSACTION ft "
        "WHERE ft.PRODUCT_ID NOT IN (SELECT PRODUCT_ID FROM DIM_PRODUCT)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan transactions by PRODUCT_ID"


# ---- RI-09 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri09_detect_orphan_with_nonexistent_account_key(sf_clone_cursor):
    """RI-09 (Negative): Detect orphan when dimension record is missing.

    Inserts a fact row with a non-existent ACCOUNT_KEY into the clone schema,
    verifies the orphan is detected, then rolls back.
    """
    # Use an ACCOUNT_KEY that certainly does not exist
    fake_key = 999999999

    sf_clone_cursor.execute("BEGIN")
    try:
        sf_clone_cursor.execute(
            "INSERT INTO FACT_TRANSACTION "
            "(TRANSACTION_ID, TRANSACTION_DATE, ACCOUNT_KEY, CUSTOMER_KEY, "
            " PRODUCT_ID, DATE_KEY, TRANSACTION_TYPE, TRANSACTION_AMOUNT) "
            "VALUES (999999999, '2025-01-01', %s, 1, 1, 20250101, 'DEBIT', 100.00)",
            (fake_key,),
        )
        rows = run_query(
            sf_clone_cursor,
            "SELECT COUNT(*) FROM FACT_TRANSACTION ft "
            "WHERE ft.ACCOUNT_KEY NOT IN (SELECT ACCOUNT_KEY FROM DIM_ACCOUNT)",
        )
        assert rows[0][0] >= 1, "Orphan detection failed — expected at least 1 orphan"
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- RI-10 ----------------------------------------------------------------
@pytest.mark.referential_integrity
def test_ri10_snapshot_customer_key_references_dim_customer(sf_cursor):
    """RI-10: Snapshot CUSTOMER_KEY references DIM_CUSTOMER."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT snap "
        "WHERE snap.CUSTOMER_KEY NOT IN (SELECT CUSTOMER_KEY FROM DIM_CUSTOMER)",
    )
    assert rows[0][0] == 0, f"Found {rows[0][0]} orphan snapshots by CUSTOMER_KEY"
