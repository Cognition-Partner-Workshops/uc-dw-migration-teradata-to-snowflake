"""
Pytest configuration and shared fixtures for migration validation tests.

Provides Snowflake (and optional Teradata) connection fixtures.
Credentials are read from environment variables — never hard-coded.
"""

import os

import pytest

try:
    import snowflake.connector as sf_connector
except ImportError:
    sf_connector = None

try:
    import teradatasql
except ImportError:
    teradatasql = None

from tests.config import (
    SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_DATABASE,
    SNOWFLAKE_PASSWORD,
    SNOWFLAKE_ROLE,
    SNOWFLAKE_SCHEMA,
    SNOWFLAKE_USER,
    SNOWFLAKE_WAREHOUSE,
    TARGET_SCHEMA,
    TERADATA_DATABASE,
    TERADATA_HOST,
    TERADATA_PASSWORD,
    TERADATA_USER,
)


# ---------------------------------------------------------------------------
# Pytest markers registration
# ---------------------------------------------------------------------------
def pytest_configure(config):
    """Register custom markers for test categories."""
    config.addinivalue_line("markers", "schema: Schema validation tests (Category 1)")
    config.addinivalue_line("markers", "row_count: Row count validation tests (Category 2)")
    config.addinivalue_line("markers", "data_integrity: Data integrity & checksum tests (Category 3)")
    config.addinivalue_line(
        "markers", "referential_integrity: Referential integrity tests (Category 4)"
    )
    config.addinivalue_line("markers", "business_logic: Business logic validation tests (Category 5)")
    config.addinivalue_line(
        "markers", "translation: Teradata-to-Snowflake translation tests (Category 6)"
    )
    config.addinivalue_line("markers", "negative: Negative tests (Category 7)")
    config.addinivalue_line("markers", "edge_case: Edge case tests (Category 8)")
    config.addinivalue_line("markers", "view_parity: View parity tests (Category 9)")
    config.addinivalue_line(
        "markers", "stored_procedure: Stored procedure parity tests (Category 10)"
    )
    config.addinivalue_line("markers", "sample_data: Sample data comparison tests (Category 11)")


# ---------------------------------------------------------------------------
# Snowflake connection fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def snowflake_conn():
    """Create a Snowflake connection for the entire test session.

    Yields the connection and closes it on teardown.
    Skips all tests if the connector is not installed or credentials
    are not configured.
    """
    if sf_connector is None:
        pytest.skip("snowflake-connector-python is not installed")

    if not SNOWFLAKE_ACCOUNT or not SNOWFLAKE_USER:
        pytest.skip(
            "Snowflake credentials not configured. "
            "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_PASSWORD env vars."
        )

    conn_params = {
        "account": SNOWFLAKE_ACCOUNT,
        "user": SNOWFLAKE_USER,
        "password": SNOWFLAKE_PASSWORD,
        "database": SNOWFLAKE_DATABASE,
        "warehouse": SNOWFLAKE_WAREHOUSE,
        "schema": SNOWFLAKE_SCHEMA,
    }
    if SNOWFLAKE_ROLE:
        conn_params["role"] = SNOWFLAKE_ROLE

    conn = sf_connector.connect(**conn_params)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def sf_cursor(snowflake_conn):
    """Provide a reusable Snowflake cursor."""
    cur = snowflake_conn.cursor()
    yield cur
    cur.close()


# ---------------------------------------------------------------------------
# Teradata connection fixture (optional)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def teradata_conn():
    """Create a Teradata connection for source-to-target comparisons.

    Yields the connection and closes it on teardown.
    Skips if the driver is not installed or credentials are missing.
    """
    if teradatasql is None:
        pytest.skip("teradatasql is not installed")

    if not TERADATA_HOST or not TERADATA_USER:
        pytest.skip(
            "Teradata credentials not configured. "
            "Set TERADATA_HOST, TERADATA_USER, and TERADATA_PASSWORD env vars."
        )

    conn = teradatasql.connect(
        host=TERADATA_HOST,
        user=TERADATA_USER,
        password=TERADATA_PASSWORD,
        database=TERADATA_DATABASE,
    )
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helper fixture: target schema name
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def target_schema():
    """Return the configured target schema name."""
    return TARGET_SCHEMA


# ---------------------------------------------------------------------------
# Helper fixture: repo root path
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def repo_root():
    """Return the absolute path to the repository root."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
