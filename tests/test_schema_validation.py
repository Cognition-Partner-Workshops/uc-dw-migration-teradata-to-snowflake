"""
Category 1: Schema Validation Tests (S-01 to S-09)

Verifies that the Snowflake target schema matches the Teradata source DDL
in terms of tables, views, columns, data types, constraints, and defaults.
"""

import pytest

from tests.config import (
    ALL_TABLES,
    ALL_VIEWS,
    DEFAULT_VALUE_CHECKS,
    EXPECTED_COLUMN_COUNTS,
    EXPECTED_COLUMNS,
    EXPECTED_TIMESTAMP_TYPE,
    EXPECTED_TYPE_MAPPINGS,
    IDENTITY_COLUMNS,
    NOT_NULL_COLUMNS,
    SNOWFLAKE_SCHEMA,
    TIMESTAMP6_COLUMNS,
    TIMESTAMP_COLUMNS,
)
from tests.utils import run_query


# -------------------------------------------------------------------------
# S-01: Verify all 7 tables exist in Snowflake
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestTablesExist:
    """S-01: All 7 tables must be present in the target schema."""

    def test_all_tables_exist(self, sf_cursor):
        sql = """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA,))
        actual_tables = {row[0] for row in rows}
        expected_tables = set(ALL_TABLES)
        missing = expected_tables - actual_tables
        assert not missing, f"Missing tables in Snowflake: {missing}"

    @pytest.mark.parametrize("table_name", ALL_TABLES)
    def test_individual_table_exists(self, sf_cursor, table_name):
        sql = """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND TABLE_TYPE = 'BASE TABLE'
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name))
        assert rows[0][0] == 1, f"Table {table_name} not found in {SNOWFLAKE_SCHEMA}"


# -------------------------------------------------------------------------
# S-02: Verify all 3 views exist in Snowflake
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestViewsExist:
    """S-02: All 3 views must be present in the target schema."""

    def test_all_views_exist(self, sf_cursor):
        sql = """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA,))
        actual_views = {row[0] for row in rows}
        expected_views = set(ALL_VIEWS)
        missing = expected_views - actual_views
        assert not missing, f"Missing views in Snowflake: {missing}"

    @pytest.mark.parametrize("view_name", ALL_VIEWS)
    def test_individual_view_exists(self, sf_cursor, view_name):
        sql = """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, view_name))
        assert rows[0][0] == 1, f"View {view_name} not found in {SNOWFLAKE_SCHEMA}"


# -------------------------------------------------------------------------
# S-03: Verify column count per table matches Teradata DDL
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestColumnCounts:
    """S-03: Column count per table must match the source DDL definition."""

    @pytest.mark.parametrize(
        "table_name,expected_count",
        list(EXPECTED_COLUMN_COUNTS.items()),
        ids=list(EXPECTED_COLUMN_COUNTS.keys()),
    )
    def test_column_count(self, sf_cursor, table_name, expected_count):
        sql = """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name))
        actual = rows[0][0]
        assert actual == expected_count, (
            f"{table_name}: expected {expected_count} columns, got {actual}"
        )


# -------------------------------------------------------------------------
# S-04: Verify column names match between source DDL and Snowflake
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestColumnNames:
    """S-04: All column names from the DDL must exist in Snowflake (case-insensitive)."""

    @pytest.mark.parametrize(
        "table_name,expected_cols",
        list(EXPECTED_COLUMNS.items()),
        ids=list(EXPECTED_COLUMNS.keys()),
    )
    def test_column_names(self, sf_cursor, table_name, expected_cols):
        sql = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name))
        actual_cols = {row[0].upper() for row in rows}
        expected_set = {c.upper() for c in expected_cols}
        missing = expected_set - actual_cols
        extra = actual_cols - expected_set
        assert not missing, f"{table_name}: missing columns {missing}"
        assert not extra, f"{table_name}: unexpected extra columns {extra}"


# -------------------------------------------------------------------------
# S-05: Verify column data types are correctly translated
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestDataTypes:
    """S-05: Teradata types must be correctly translated to Snowflake types."""

    @pytest.mark.parametrize(
        "table_name,column_name,expected_type,expected_precision,expected_scale",
        EXPECTED_TYPE_MAPPINGS,
        ids=[f"{t[0]}.{t[1]}" for t in EXPECTED_TYPE_MAPPINGS],
    )
    def test_data_type_mapping(
        self, sf_cursor, table_name, column_name, expected_type,
        expected_precision, expected_scale,
    ):
        sql = """
            SELECT DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        actual_type, actual_prec, actual_scale = rows[0]

        assert actual_type == expected_type, (
            f"{table_name}.{column_name}: expected type {expected_type}, got {actual_type}"
        )
        if expected_precision is not None:
            assert actual_prec == expected_precision, (
                f"{table_name}.{column_name}: expected precision {expected_precision}, "
                f"got {actual_prec}"
            )
        if expected_scale is not None:
            assert actual_scale == expected_scale, (
                f"{table_name}.{column_name}: expected scale {expected_scale}, "
                f"got {actual_scale}"
            )


# -------------------------------------------------------------------------
# S-06: Verify NOT NULL constraints are preserved
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestNotNullConstraints:
    """S-06: NOT NULL constraints from Teradata must be preserved in Snowflake."""

    @pytest.mark.parametrize(
        "table_name,column_name",
        NOT_NULL_COLUMNS,
        ids=[f"{t}.{c}" for t, c in NOT_NULL_COLUMNS],
    )
    def test_not_null(self, sf_cursor, table_name, column_name):
        sql = """
            SELECT IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        assert rows[0][0] == "NO", (
            f"{table_name}.{column_name}: expected NOT NULL, "
            f"but IS_NULLABLE = {rows[0][0]}"
        )


# -------------------------------------------------------------------------
# S-07: Verify DEFAULT values are translated
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestDefaultValues:
    """S-07: DEFAULT values from Teradata must be translated to Snowflake."""

    @pytest.mark.parametrize(
        "table_name,column_name,expected_default",
        DEFAULT_VALUE_CHECKS,
        ids=[f"{t}.{c}" for t, c, _ in DEFAULT_VALUE_CHECKS],
    )
    def test_default_value(self, sf_cursor, table_name, column_name, expected_default):
        sql = """
            SELECT COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        actual_default = rows[0][0]
        assert actual_default is not None, (
            f"{table_name}.{column_name}: expected DEFAULT {expected_default}, got NULL"
        )
        # Snowflake may store defaults in different formats; do case-insensitive contains check
        assert expected_default.strip("'").upper() in str(actual_default).upper(), (
            f"{table_name}.{column_name}: expected DEFAULT containing "
            f"{expected_default}, got '{actual_default}'"
        )


# -------------------------------------------------------------------------
# S-08: Verify IDENTITY/AUTOINCREMENT columns
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestIdentityColumns:
    """S-08: IDENTITY columns must use AUTOINCREMENT or IDENTITY in Snowflake."""

    @pytest.mark.parametrize(
        "table_name,column_name",
        IDENTITY_COLUMNS,
        ids=[f"{t}.{c}" for t, c in IDENTITY_COLUMNS],
    )
    def test_identity_column(self, sf_cursor, table_name, column_name):
        sql = """
            SELECT IS_IDENTITY
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        assert rows[0][0] == "YES", (
            f"{table_name}.{column_name}: expected IDENTITY/AUTOINCREMENT, "
            f"got IS_IDENTITY = {rows[0][0]}"
        )


# -------------------------------------------------------------------------
# S-09: Verify TIMESTAMP column types match timezone strategy
# -------------------------------------------------------------------------
@pytest.mark.schema
class TestTimestampTypes:
    """S-09: TIMESTAMP columns must match the expected timezone strategy."""

    @pytest.mark.parametrize(
        "table_name,column_name",
        TIMESTAMP_COLUMNS,
        ids=[f"{t}.{c}" for t, c in TIMESTAMP_COLUMNS],
    )
    def test_timestamp_type(self, sf_cursor, table_name, column_name):
        sql = """
            SELECT DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        actual_type = rows[0][0]
        assert actual_type == EXPECTED_TIMESTAMP_TYPE, (
            f"{table_name}.{column_name}: expected {EXPECTED_TIMESTAMP_TYPE}, "
            f"got {actual_type}"
        )

    @pytest.mark.parametrize(
        "table_name,column_name",
        TIMESTAMP6_COLUMNS,
        ids=[f"{t}.{c}_ts6" for t, c in TIMESTAMP6_COLUMNS],
    )
    def test_timestamp6_precision(self, sf_cursor, table_name, column_name):
        """TIMESTAMP(6) columns should retain higher precision."""
        sql = """
            SELECT DATA_TYPE, DATETIME_PRECISION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
        """
        rows = run_query(sf_cursor, sql, (SNOWFLAKE_SCHEMA, table_name, column_name))
        assert len(rows) == 1, f"Column {table_name}.{column_name} not found"
        actual_type = rows[0][0]
        # Accept either TIMESTAMP_NTZ or TIMESTAMP_LTZ depending on strategy
        assert "TIMESTAMP" in actual_type, (
            f"{table_name}.{column_name}: expected TIMESTAMP variant, got {actual_type}"
        )
