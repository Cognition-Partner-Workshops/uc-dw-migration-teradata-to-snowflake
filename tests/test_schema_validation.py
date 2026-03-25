"""
Category 1: Schema Validation (Positive Tests)
Test IDs: S-01 through S-09

Verifies that the Snowflake target schema faithfully reproduces the
Teradata source DDL — tables, views, columns, data types, constraints,
defaults, identity columns, and timestamp types.
"""

import pytest

from tests.config import (
    EXPECTED_COLUMN_COUNTS,
    EXPECTED_COLUMNS,
    EXPECTED_DEFAULTS,
    NOT_NULL_COLUMNS,
    SCHEMA_NAME,
    TABLES,
    TIMESTAMP_TYPE,
    VIEWS,
)
from tests.utils import run_query


# ---- S-01 ----------------------------------------------------------------
@pytest.mark.schema
def test_s01_all_tables_exist(sf_cursor):
    """S-01: Verify all 7 tables exist in Snowflake."""
    rows = run_query(
        sf_cursor,
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_NAME",
        (SCHEMA_NAME,),
    )
    existing_tables = {r[0] for r in rows}
    for table in TABLES:
        assert table in existing_tables, f"Table {table} missing in Snowflake"


# ---- S-02 ----------------------------------------------------------------
@pytest.mark.schema
def test_s02_all_views_exist(sf_cursor):
    """S-02: Verify all 3 views exist in Snowflake."""
    rows = run_query(
        sf_cursor,
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS "
        "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
        (SCHEMA_NAME,),
    )
    existing_views = {r[0] for r in rows}
    for view in VIEWS:
        assert view in existing_views, f"View {view} missing in Snowflake"


# ---- S-03 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize("table_name", TABLES)
def test_s03_column_count(sf_cursor, table_name):
    """S-03: Verify column count per table matches Teradata DDL."""
    rows = run_query(
        sf_cursor,
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (SCHEMA_NAME, table_name),
    )
    actual = rows[0][0]
    expected = EXPECTED_COLUMN_COUNTS[table_name]
    assert actual == expected, (
        f"{table_name}: expected {expected} columns, got {actual}"
    )


# ---- S-04 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize("table_name", TABLES)
def test_s04_column_names(sf_cursor, table_name):
    """S-04: Verify column names match between source DDL and Snowflake."""
    rows = run_query(
        sf_cursor,
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY ORDINAL_POSITION",
        (SCHEMA_NAME, table_name),
    )
    actual_cols = {r[0].upper() for r in rows}
    expected_cols = {c.upper() for c in EXPECTED_COLUMNS[table_name]}
    missing = expected_cols - actual_cols
    extra = actual_cols - expected_cols
    assert not missing, f"{table_name}: missing columns {missing}"
    assert not extra, f"{table_name}: unexpected columns {extra}"


# ---- S-05 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize(
    "table_name,column_name,expected_type",
    [
        ("DIM_CUSTOMER", "CUSTOMER_ID", "NUMBER"),
        ("DIM_CUSTOMER", "CUSTOMER_KEY", "NUMBER"),
        ("DIM_CUSTOMER", "FIRST_NAME", "VARCHAR"),  # was VARCHAR in TD
        ("DIM_CUSTOMER", "RISK_SCORE", "NUMBER"),
        ("DIM_CUSTOMER", "GENDER", "VARCHAR"),  # CHAR -> VARCHAR
        ("DIM_CUSTOMER", "IS_ACTIVE", "NUMBER"),  # BYTEINT -> NUMBER
        ("DIM_CUSTOMER", "EFFECTIVE_FROM", "TIMESTAMP_NTZ"),
        ("FACT_TRANSACTION", "TRANSACTION_AMOUNT", "NUMBER"),
        ("FACT_TRANSACTION", "TRANSACTION_TS", "TIMESTAMP_NTZ"),
        ("FACT_TRANSACTION", "TRANSACTION_DATE", "DATE"),
        ("DIM_DATE", "DATE_KEY", "NUMBER"),
        ("DIM_DATE", "CALENDAR_DATE", "DATE"),
    ],
)
def test_s05_data_type_translation(sf_cursor, table_name, column_name, expected_type):
    """S-05: Verify column data types are correctly translated."""
    rows = run_query(
        sf_cursor,
        "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (SCHEMA_NAME, table_name, column_name),
    )
    assert rows, f"Column {table_name}.{column_name} not found"
    actual_type = rows[0][0]
    assert actual_type == expected_type, (
        f"{table_name}.{column_name}: expected type {expected_type}, "
        f"got {actual_type}"
    )


# ---- S-06 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize("table_name", list(NOT_NULL_COLUMNS.keys()))
def test_s06_not_null_constraints(sf_cursor, table_name):
    """S-06: Verify NOT NULL constraints are preserved."""
    rows = run_query(
        sf_cursor,
        "SELECT COLUMN_NAME, IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (SCHEMA_NAME, table_name),
    )
    nullable_map = {r[0]: r[1] for r in rows}
    for col in NOT_NULL_COLUMNS[table_name]:
        assert col in nullable_map, f"{table_name}.{col} not found"
        assert nullable_map[col] == "NO", (
            f"{table_name}.{col} should be NOT NULL but is nullable"
        )


# ---- S-07 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize(
    "table_name,column_name,expected_default_fragment",
    [
        ("DIM_CUSTOMER", "IS_ACTIVE", "1"),
        ("DIM_CUSTOMER", "COUNTRY_CODE", "NOR"),
        ("DIM_CUSTOMER", "CURRENT_FLAG", "Y"),
    ],
)
def test_s07_default_values(sf_cursor, table_name, column_name, expected_default_fragment):
    """S-07: Verify DEFAULT values are translated."""
    rows = run_query(
        sf_cursor,
        "SELECT COLUMN_DEFAULT FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (SCHEMA_NAME, table_name, column_name),
    )
    assert rows, f"{table_name}.{column_name} not found"
    default_val = str(rows[0][0]) if rows[0][0] is not None else ""
    assert expected_default_fragment in default_val, (
        f"{table_name}.{column_name}: expected default containing "
        f"'{expected_default_fragment}', got '{default_val}'"
    )


# ---- S-08 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize(
    "table_name,column_name",
    [
        ("DIM_CUSTOMER", "CUSTOMER_KEY"),
        ("DIM_ACCOUNT", "ACCOUNT_KEY"),
    ],
)
def test_s08_identity_columns(sf_cursor, table_name, column_name):
    """S-08: Verify IDENTITY/AUTOINCREMENT columns."""
    rows = run_query(
        sf_cursor,
        "SELECT IS_IDENTITY FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (SCHEMA_NAME, table_name, column_name),
    )
    assert rows, f"{table_name}.{column_name} not found"
    assert rows[0][0] == "YES", (
        f"{table_name}.{column_name} should be IDENTITY but IS_IDENTITY = {rows[0][0]}"
    )


# ---- S-09 ----------------------------------------------------------------
@pytest.mark.schema
@pytest.mark.parametrize(
    "table_name,column_name",
    [
        ("DIM_CUSTOMER", "EFFECTIVE_FROM"),
        ("DIM_CUSTOMER", "ETL_INSERT_TS"),
        ("DIM_ACCOUNT", "EFFECTIVE_FROM"),
        ("FACT_TRANSACTION", "ETL_INSERT_TS"),
    ],
)
def test_s09_timestamp_types(sf_cursor, table_name, column_name):
    """S-09: Verify TIMESTAMP column types match timezone strategy."""
    rows = run_query(
        sf_cursor,
        "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (SCHEMA_NAME, table_name, column_name),
    )
    assert rows, f"{table_name}.{column_name} not found"
    actual = rows[0][0]
    assert actual == TIMESTAMP_TYPE, (
        f"{table_name}.{column_name}: expected {TIMESTAMP_TYPE}, got {actual}"
    )
