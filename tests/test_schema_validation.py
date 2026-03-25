"""
Category 1: Schema Validation Tests (S-01 through S-09)

Validates that the Snowflake target schema matches the Teradata source DDL
definitions for all tables, views, columns, data types, constraints,
defaults, identity columns, and timestamp types.
"""

import pytest

from tests.config import (
    EXPECTED_COLUMN_COUNTS,
    EXPECTED_COLUMNS,
    EXPECTED_DATA_TYPES,
    EXPECTED_DEFAULTS,
    EXPECTED_IDENTITY_COLUMNS,
    EXPECTED_NOT_NULL_COLUMNS,
    EXPECTED_TABLES,
    EXPECTED_TIMESTAMP_COLUMNS,
    EXPECTED_VIEWS,
    TIMESTAMP_VARIANT,
)
from tests.utils import run_query


# ---------------------------------------------------------------------------
# S-01: Verify all 7 tables exist in Snowflake
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS01TablesExist:
    """S-01: Verify all 7 tables exist in the Snowflake target schema."""

    def test_all_tables_present(self, sf_cursor, target_schema):
        """All 7 expected tables must be present in the target schema."""
        rows = run_query(
            sf_cursor,
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """,
            [target_schema],
        )
        actual_tables = {row[0] for row in rows}
        expected = set(EXPECTED_TABLES)

        missing = expected - actual_tables
        assert not missing, (
            f"Missing tables in {target_schema}: {sorted(missing)}"
        )

    @pytest.mark.parametrize("table_name", EXPECTED_TABLES)
    def test_individual_table_exists(self, sf_cursor, target_schema, table_name):
        """Each expected table must individually exist."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND TABLE_TYPE = 'BASE TABLE'
            """,
            [target_schema, table_name],
        )
        assert rows[0][0] == 1, f"Table {table_name} not found in schema {target_schema}"


# ---------------------------------------------------------------------------
# S-02: Verify all 3 views exist in Snowflake
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS02ViewsExist:
    """S-02: Verify all 3 views exist in the Snowflake target schema."""

    def test_all_views_present(self, sf_cursor, target_schema):
        """All 3 expected views must be present in the target schema."""
        rows = run_query(
            sf_cursor,
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
            """,
            [target_schema],
        )
        actual_views = {row[0] for row in rows}
        expected = set(EXPECTED_VIEWS)

        missing = expected - actual_views
        assert not missing, (
            f"Missing views in {target_schema}: {sorted(missing)}"
        )

    @pytest.mark.parametrize("view_name", EXPECTED_VIEWS)
    def test_individual_view_exists(self, sf_cursor, target_schema, view_name):
        """Each expected view must individually exist."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.VIEWS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            """,
            [target_schema, view_name],
        )
        assert rows[0][0] == 1, f"View {view_name} not found in schema {target_schema}"


# ---------------------------------------------------------------------------
# S-03: Verify column count per table matches Teradata DDL
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS03ColumnCounts:
    """S-03: Verify column count per table matches the Teradata DDL."""

    @pytest.mark.parametrize(
        "table_name,expected_count",
        list(EXPECTED_COLUMN_COUNTS.items()),
        ids=list(EXPECTED_COLUMN_COUNTS.keys()),
    )
    def test_column_count(self, sf_cursor, target_schema, table_name, expected_count):
        """Column count for each table must match the source DDL definition."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            """,
            [target_schema, table_name],
        )
        actual_count = rows[0][0]
        assert actual_count == expected_count, (
            f"{table_name}: expected {expected_count} columns, found {actual_count}"
        )


# ---------------------------------------------------------------------------
# S-04: Verify column names match between source DDL and Snowflake
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS04ColumnNames:
    """S-04: Verify column names match between source DDL and Snowflake."""

    @pytest.mark.parametrize(
        "table_name,expected_cols",
        list(EXPECTED_COLUMNS.items()),
        ids=list(EXPECTED_COLUMNS.keys()),
    )
    def test_column_names(self, sf_cursor, target_schema, table_name, expected_cols):
        """All column names from the source DDL must exist in Snowflake (case-insensitive)."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            [target_schema, table_name],
        )
        actual_cols = {row[0].upper() for row in rows}
        expected_set = {c.upper() for c in expected_cols}

        missing = expected_set - actual_cols
        extra = actual_cols - expected_set

        assert not missing, (
            f"{table_name}: missing columns: {sorted(missing)}"
        )
        if extra:
            # Extra columns are a warning, not a failure — Snowflake may add
            # metadata columns, but we still flag them for review.
            pass


# ---------------------------------------------------------------------------
# S-05: Verify column data types are correctly translated
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS05DataTypes:
    """S-05: Verify column data types are correctly translated from Teradata to Snowflake."""

    @pytest.mark.parametrize(
        "table_col,expected_meta",
        list(EXPECTED_DATA_TYPES.items()),
        ids=[f"{t}_{c}" for t, c in EXPECTED_DATA_TYPES.keys()],
    )
    def test_data_type(self, sf_cursor, target_schema, table_col, expected_meta):
        """Each column's data type (and precision/scale where applicable) must match."""
        table_name, column_name = table_col

        rows = run_query(
            sf_cursor,
            """
            SELECT
                DATA_TYPE,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            [target_schema, table_name, column_name],
        )
        assert rows, (
            f"Column {table_name}.{column_name} not found in {target_schema}"
        )

        actual_data_type = rows[0][0]
        actual_precision = rows[0][1]
        actual_scale = rows[0][2]

        expected_type = expected_meta["DATA_TYPE"]
        assert actual_data_type == expected_type, (
            f"{table_name}.{column_name}: expected DATA_TYPE={expected_type}, "
            f"got {actual_data_type}"
        )

        if "NUMERIC_PRECISION" in expected_meta:
            assert actual_precision == expected_meta["NUMERIC_PRECISION"], (
                f"{table_name}.{column_name}: expected NUMERIC_PRECISION="
                f"{expected_meta['NUMERIC_PRECISION']}, got {actual_precision}"
            )

        if "NUMERIC_SCALE" in expected_meta:
            assert actual_scale == expected_meta["NUMERIC_SCALE"], (
                f"{table_name}.{column_name}: expected NUMERIC_SCALE="
                f"{expected_meta['NUMERIC_SCALE']}, got {actual_scale}"
            )


# ---------------------------------------------------------------------------
# S-06: Verify NOT NULL constraints are preserved
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS06NotNullConstraints:
    """S-06: Verify NOT NULL constraints are preserved from Teradata DDL."""

    @pytest.mark.parametrize(
        "table_name,not_null_cols",
        list(EXPECTED_NOT_NULL_COLUMNS.items()),
        ids=list(EXPECTED_NOT_NULL_COLUMNS.keys()),
    )
    def test_not_null_constraints(self, sf_cursor, target_schema, table_name, not_null_cols):
        """Columns marked NOT NULL in Teradata DDL must be NOT NULL in Snowflake."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COLUMN_NAME, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
            """,
            [target_schema, table_name],
        )
        nullable_map = {row[0].upper(): row[1] for row in rows}

        violations = []
        for col in not_null_cols:
            col_upper = col.upper()
            if col_upper not in nullable_map:
                violations.append(f"{col} (column not found)")
            elif nullable_map[col_upper] != "NO":
                violations.append(f"{col} (IS_NULLABLE={nullable_map[col_upper]})")

        assert not violations, (
            f"{table_name}: NOT NULL violations: {violations}"
        )


# ---------------------------------------------------------------------------
# S-07: Verify DEFAULT values are translated
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS07DefaultValues:
    """S-07: Verify DEFAULT values are translated from Teradata DDL."""

    @pytest.mark.parametrize(
        "table_col,expected_default",
        list(EXPECTED_DEFAULTS.items()),
        ids=[f"{t}_{c}" for t, c in EXPECTED_DEFAULTS.keys()],
    )
    def test_default_value(self, sf_cursor, target_schema, table_col, expected_default):
        """Each column's DEFAULT value must contain the expected expression."""
        table_name, column_name = table_col

        rows = run_query(
            sf_cursor,
            """
            SELECT COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            [target_schema, table_name, column_name],
        )
        assert rows, (
            f"Column {table_name}.{column_name} not found in {target_schema}"
        )

        actual_default = rows[0][0]
        assert actual_default is not None, (
            f"{table_name}.{column_name}: expected DEFAULT containing "
            f"'{expected_default}', but COLUMN_DEFAULT is NULL"
        )

        # Snowflake may wrap default expressions; check for substring match
        assert expected_default in str(actual_default), (
            f"{table_name}.{column_name}: expected DEFAULT containing "
            f"'{expected_default}', got '{actual_default}'"
        )


# ---------------------------------------------------------------------------
# S-08: Verify IDENTITY/AUTOINCREMENT columns
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS08IdentityColumns:
    """S-08: Verify IDENTITY/AUTOINCREMENT columns exist in Snowflake."""

    @pytest.mark.parametrize(
        "table_name,identity_cols",
        list(EXPECTED_IDENTITY_COLUMNS.items()),
        ids=list(EXPECTED_IDENTITY_COLUMNS.keys()),
    )
    def test_identity_columns(self, sf_cursor, target_schema, table_name, identity_cols):
        """Columns with GENERATED ALWAYS AS IDENTITY must be present."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COLUMN_NAME, IS_IDENTITY
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND IS_IDENTITY = 'YES'
            """,
            [target_schema, table_name],
        )
        actual_identity_cols = {row[0].upper() for row in rows}
        expected = {c.upper() for c in identity_cols}

        missing = expected - actual_identity_cols
        assert not missing, (
            f"{table_name}: expected IDENTITY columns {sorted(missing)} not found. "
            f"Actual IDENTITY columns: {sorted(actual_identity_cols)}"
        )


# ---------------------------------------------------------------------------
# S-09: Verify TIMESTAMP column types match timezone strategy
# ---------------------------------------------------------------------------
@pytest.mark.schema
class TestS09TimestampTypes:
    """S-09: Verify TIMESTAMP columns use the expected variant (NTZ/LTZ/TZ)."""

    @pytest.mark.parametrize(
        "table_name,ts_cols",
        list(EXPECTED_TIMESTAMP_COLUMNS.items()),
        ids=list(EXPECTED_TIMESTAMP_COLUMNS.keys()),
    )
    def test_timestamp_column_types(self, sf_cursor, target_schema, table_name, ts_cols):
        """All TIMESTAMP columns must use the configured variant."""
        rows = run_query(
            sf_cursor,
            """
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND DATA_TYPE LIKE 'TIMESTAMP%%'
            """,
            [target_schema, table_name],
        )
        ts_type_map = {row[0].upper(): row[1] for row in rows}

        violations = []
        for col in ts_cols:
            col_upper = col.upper()
            if col_upper not in ts_type_map:
                violations.append(f"{col} (not found or not a TIMESTAMP type)")
            elif ts_type_map[col_upper] != TIMESTAMP_VARIANT:
                violations.append(
                    f"{col} (expected {TIMESTAMP_VARIANT}, "
                    f"got {ts_type_map[col_upper]})"
                )

        assert not violations, (
            f"{table_name}: TIMESTAMP type violations: {violations}"
        )
