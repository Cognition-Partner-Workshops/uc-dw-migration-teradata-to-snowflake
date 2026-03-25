"""
Pytest fixtures for Snowflake (and optional Teradata) connectivity.

Credentials are read from environment variables — never hardcoded.
"""

import pytest
import snowflake.connector

from tests.config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE,
    SNOWFLAKE_SCHEMA,
    SNOWFLAKE_USER,
    SNOWFLAKE_WAREHOUSE,
    TERADATA_DATABASE,
    TERADATA_HOST,
    TERADATA_PASSWORD,
    TERADATA_USER,
)


# ---------------------------------------------------------------------------
# Snowflake fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sf_connection():
    """Session-scoped Snowflake connection. Cleaned up after all tests."""
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        database=SNOWFLAKE_DATABASE,
        warehouse=SNOWFLAKE_WAREHOUSE,
        schema=SNOWFLAKE_SCHEMA,
        role=SNOWFLAKE_ROLE or None,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def sf_cursor(sf_connection):
    """Session-scoped Snowflake cursor."""
    cur = sf_connection.cursor()
    yield cur
    cur.close()


# ---------------------------------------------------------------------------
# Teradata fixtures (optional — skipped when host is not configured)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def td_connection():
    """Session-scoped Teradata connection. Skipped if credentials missing."""
    if not TERADATA_HOST:
        pytest.skip("Teradata connection not configured (TERADATA_HOST is empty)")

    try:
        import teradatasql  # noqa: F811
    except ImportError:
        pytest.skip("teradatasql package not installed")

    conn = teradatasql.connect(
        host=TERADATA_HOST,
        user=TERADATA_USER,
        password=TERADATA_PASSWORD,
        database=TERADATA_DATABASE,
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def td_cursor(td_connection):
    """Session-scoped Teradata cursor."""
    cur = td_connection.cursor()
    yield cur
    cur.close()


# ---------------------------------------------------------------------------
# Pytest markers registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Register custom markers to avoid warnings."""
    config.addinivalue_line("markers", "schema: Schema validation tests (Category 1)")
    config.addinivalue_line("markers", "row_count: Row count validation tests (Category 2)")
    config.addinivalue_line("markers", "data_integrity: Data integrity & checksum tests (Category 3)")
    config.addinivalue_line(
        "markers",
        "referential_integrity: Referential integrity tests (Category 4)",
    )
    config.addinivalue_line("markers", "business_logic: Business logic validation tests (Category 5)")
    config.addinivalue_line("markers", "translation: Teradata-to-Snowflake translation tests (Category 6)")
    config.addinivalue_line("markers", "negative: Negative / destructive tests (Category 7)")
    config.addinivalue_line("markers", "edge_case: Edge case tests (Category 8)")
    config.addinivalue_line("markers", "view_parity: View parity tests (Category 9)")
    config.addinivalue_line("markers", "stored_procedure: Stored procedure parity tests (Category 10)")
    config.addinivalue_line("markers", "sample_data: Sample data comparison tests (Category 11)")
