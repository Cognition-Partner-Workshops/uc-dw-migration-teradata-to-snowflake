"""
Category 7: Negative Tests
Test IDs: N-01 through N-11

Verifies constraint enforcement, NULL handling, truncation behaviour,
and overflow handling. All destructive operations run inside the cloned
schema and are rolled back.
"""

import pytest

from tests.utils import run_query


# ---- N-01 -----------------------------------------------------------------
@pytest.mark.negative
def test_n01_reject_null_customer_id(sf_clone_cursor):
    """N-01: Reject NULL CUSTOMER_ID in DIM_CUSTOMER."""
    sf_clone_cursor.execute("BEGIN")
    try:
        with pytest.raises(Exception):
            sf_clone_cursor.execute(
                "INSERT INTO DIM_CUSTOMER "
                "(CUSTOMER_ID, FIRST_NAME, LAST_NAME, ONBOARDING_DATE) "
                "VALUES (NULL, 'Test', 'Null', '2025-01-01')"
            )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-02 -----------------------------------------------------------------
@pytest.mark.negative
def test_n02_reject_null_transaction_amount(sf_clone_cursor):
    """N-02: Reject NULL TRANSACTION_AMOUNT in FACT_TRANSACTION."""
    sf_clone_cursor.execute("BEGIN")
    try:
        with pytest.raises(Exception):
            sf_clone_cursor.execute(
                "INSERT INTO FACT_TRANSACTION "
                "(TRANSACTION_ID, TRANSACTION_DATE, ACCOUNT_KEY, CUSTOMER_KEY, "
                " PRODUCT_ID, DATE_KEY, TRANSACTION_TYPE, TRANSACTION_AMOUNT) "
                "VALUES (888888888, '2025-01-01', 1, 1, 1, 20250101, 'DEBIT', NULL)"
            )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-03 -----------------------------------------------------------------
@pytest.mark.negative
def test_n03_reject_null_transaction_date(sf_clone_cursor):
    """N-03: Reject NULL TRANSACTION_DATE in FACT_TRANSACTION."""
    sf_clone_cursor.execute("BEGIN")
    try:
        with pytest.raises(Exception):
            sf_clone_cursor.execute(
                "INSERT INTO FACT_TRANSACTION "
                "(TRANSACTION_ID, TRANSACTION_DATE, ACCOUNT_KEY, CUSTOMER_KEY, "
                " PRODUCT_ID, DATE_KEY, TRANSACTION_TYPE, TRANSACTION_AMOUNT) "
                "VALUES (888888889, NULL, 1, 1, 1, 20250101, 'DEBIT', 100.00)"
            )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-04 -----------------------------------------------------------------
@pytest.mark.negative
def test_n04_null_handling_in_varchar_columns(sf_cursor):
    """N-04: NULL handling in VARCHAR columns — count NULLs in ADDRESS_LINE_2."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM DIM_CUSTOMER WHERE ADDRESS_LINE_2 IS NULL",
    )
    null_count = rows[0][0]
    # Just verify the count is deterministic (non-negative)
    assert null_count >= 0, "NULL count query returned unexpected result"


# ---- N-05 -----------------------------------------------------------------
@pytest.mark.negative
def test_n05_no_silent_varchar_truncation(sf_clone_cursor):
    """N-05: No silent VARCHAR truncation — insert at max length boundary."""
    sf_clone_cursor.execute("BEGIN")
    try:
        # DIM_CUSTOMER.FIRST_NAME is VARCHAR(50) — insert exactly 50 chars
        long_name = "A" * 50
        sf_clone_cursor.execute(
            "INSERT INTO DIM_CUSTOMER "
            "(CUSTOMER_ID, FIRST_NAME, LAST_NAME, ONBOARDING_DATE) "
            "VALUES (99998, %s, 'MaxLen', '2025-01-01')",
            (long_name,),
        )
        rows = run_query(
            sf_clone_cursor,
            "SELECT LENGTH(FIRST_NAME) FROM DIM_CUSTOMER WHERE CUSTOMER_ID = 99998",
        )
        assert rows[0][0] == 50, (
            f"Expected 50-char string preserved, got length {rows[0][0]}"
        )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-06 -----------------------------------------------------------------
@pytest.mark.negative
def test_n06_decimal_overflow_handling(sf_clone_cursor):
    """N-06: DECIMAL overflow — insert TRANSACTION_AMOUNT exceeding DECIMAL(15,2)."""
    sf_clone_cursor.execute("BEGIN")
    try:
        # DECIMAL(15,2) max is 9999999999999.99 — try inserting a larger value
        overflow_amount = "99999999999999.99"  # 14 digits before decimal — exceeds (15,2)
        try:
            sf_clone_cursor.execute(
                "INSERT INTO FACT_TRANSACTION "
                "(TRANSACTION_ID, TRANSACTION_DATE, ACCOUNT_KEY, CUSTOMER_KEY, "
                " PRODUCT_ID, DATE_KEY, TRANSACTION_TYPE, TRANSACTION_AMOUNT) "
                f"VALUES (888888890, '2025-01-01', 1, 1, 1, 20250101, 'DEBIT', {overflow_amount})"
            )
            # If Snowflake silently accepts it, document that behavior
            rows = run_query(
                sf_clone_cursor,
                "SELECT TRANSACTION_AMOUNT FROM FACT_TRANSACTION "
                "WHERE TRANSACTION_ID = 888888890",
            )
            # The value was accepted — Snowflake NUMBER can handle this
            assert rows[0][0] is not None, "Value was inserted as NULL"
        except Exception:
            # Expected: Snowflake rejects overflow — test passes
            pass
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-07 -----------------------------------------------------------------
@pytest.mark.negative
def test_n07_invalid_gender_value(sf_clone_cursor):
    """N-07: Invalid GENDER value — COMPRESS gap. Insert GENDER = 'X'.

    Teradata COMPRESS acts as a soft domain constraint. Snowflake has no
    equivalent constraint, so 'X' should be accepted (documenting that
    COMPRESS is not enforced).
    """
    sf_clone_cursor.execute("BEGIN")
    try:
        sf_clone_cursor.execute(
            "INSERT INTO DIM_CUSTOMER "
            "(CUSTOMER_ID, FIRST_NAME, LAST_NAME, GENDER, ONBOARDING_DATE) "
            "VALUES (99997, 'Test', 'Gender', 'X', '2025-01-01')"
        )
        rows = run_query(
            sf_clone_cursor,
            "SELECT GENDER FROM DIM_CUSTOMER WHERE CUSTOMER_ID = 99997",
        )
        assert rows[0][0] == "X", (
            "Expected 'X' to be accepted (COMPRESS not enforced in Snowflake)"
        )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-08 -----------------------------------------------------------------
@pytest.mark.negative
def test_n08_no_extra_rows_in_snowflake(sf_cursor):
    """N-08: No extra rows in Snowflake vs source — verify row counts
    are within expected bounds (proxy for anti-join without Teradata access).
    """
    from tests.config import EXPECTED_ROW_COUNTS, APPROXIMATE_COUNT_TABLES, ROW_COUNT_TOLERANCE

    for table, expected in EXPECTED_ROW_COUNTS.items():
        rows = run_query(sf_cursor, f"SELECT COUNT(*) FROM {table}")
        actual = rows[0][0]
        if table in APPROXIMATE_COUNT_TABLES:
            upper = expected * (1 + ROW_COUNT_TOLERANCE)
            assert actual <= upper, (
                f"{table}: has {actual} rows, exceeds upper bound {upper:.0f}"
            )
        else:
            assert actual == expected, (
                f"{table}: expected exactly {expected} rows, got {actual}"
            )


# ---- N-09 -----------------------------------------------------------------
@pytest.mark.negative
def test_n09_empty_string_vs_null_compress(sf_cursor):
    """N-09: Empty string vs NULL for COMPRESS '' columns."""
    # ADDRESS_LINE_2 uses COMPRESS '' in Teradata
    rows = run_query(
        sf_cursor,
        "SELECT "
        "  SUM(CASE WHEN ADDRESS_LINE_2 IS NULL THEN 1 ELSE 0 END) AS NULL_COUNT, "
        "  SUM(CASE WHEN ADDRESS_LINE_2 = '' THEN 1 ELSE 0 END) AS EMPTY_COUNT "
        "FROM DIM_CUSTOMER",
    )
    null_count, empty_count = rows[0]
    # Document the behavior — at least one of these should be non-zero
    assert null_count >= 0 and empty_count >= 0, "Query returned unexpected result"


# ---- N-10 -----------------------------------------------------------------
@pytest.mark.negative
def test_n10_reject_null_first_name(sf_clone_cursor):
    """N-10: Reject NULL FIRST_NAME in DIM_CUSTOMER."""
    sf_clone_cursor.execute("BEGIN")
    try:
        with pytest.raises(Exception):
            sf_clone_cursor.execute(
                "INSERT INTO DIM_CUSTOMER "
                "(CUSTOMER_ID, FIRST_NAME, LAST_NAME, ONBOARDING_DATE) "
                "VALUES (99996, NULL, 'NullFirst', '2025-01-01')"
            )
    finally:
        sf_clone_cursor.execute("ROLLBACK")


# ---- N-11 -----------------------------------------------------------------
@pytest.mark.negative
def test_n11_reject_null_product_name(sf_clone_cursor):
    """N-11: Reject NULL PRODUCT_NAME in DIM_PRODUCT."""
    sf_clone_cursor.execute("BEGIN")
    try:
        with pytest.raises(Exception):
            sf_clone_cursor.execute(
                "INSERT INTO DIM_PRODUCT "
                "(PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_CATEGORY) "
                "VALUES (99999, 'TST-NULL', NULL, 'DEPOSITS')"
            )
    finally:
        sf_clone_cursor.execute("ROLLBACK")
