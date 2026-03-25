"""
Pytest configuration and shared fixtures for Snowflake migration validation.

Fixtures provide managed Snowflake (and optionally Teradata) connections
that are automatically cleaned up after each test session.
"""

import pytest
import snowflake.connector

from tests.config import SNOWFLAKE_CONFIG, TERADATA_CONFIG, TERADATA_AVAILABLE, CLONE_SCHEMA, SCHEMA_NAME


# ---------------------------------------------------------------------------
# Pytest markers registration
# ---------------------------------------------------------------------------
def pytest_configure(config):
    """Register custom markers so pytest does not emit warnings."""
    config.addinivalue_line("markers", "schema: Schema validation tests")
    config.addinivalue_line("markers", "row_count: Row count validation tests")
    config.addinivalue_line("markers", "data_integrity: Data integrity & checksum tests")
    config.addinivalue_line("markers", "referential_integrity: Referential integrity tests")
    config.addinivalue_line("markers", "business_logic: Business logic validation tests")
    config.addinivalue_line("markers", "translation: Teradata-to-Snowflake translation parity tests")
    config.addinivalue_line("markers", "negative: Negative / constraint enforcement tests")
    config.addinivalue_line("markers", "edge_case: Edge case & boundary tests")
    config.addinivalue_line("markers", "view_parity: View parity tests")
    config.addinivalue_line("markers", "stored_procedure: Stored procedure / macro parity tests")
    config.addinivalue_line("markers", "sample_data: Sample data comparison tests")


# ---------------------------------------------------------------------------
# Snowflake connection fixture (session-scoped)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sf_connection():
    """Return a Snowflake connection for the entire test session."""
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_CONFIG["account"],
        user=SNOWFLAKE_CONFIG["user"],
        password=SNOWFLAKE_CONFIG["password"],
        database=SNOWFLAKE_CONFIG["database"],
        warehouse=SNOWFLAKE_CONFIG["warehouse"],
        schema=SNOWFLAKE_CONFIG["schema"],
        role=SNOWFLAKE_CONFIG["role"],
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def sf_cursor(sf_connection):
    """Return a Snowflake cursor for the entire test session."""
    cur = sf_connection.cursor()
    yield cur
    cur.close()


# ---------------------------------------------------------------------------
# Snowflake clone schema fixture (session-scoped, for negative tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sf_clone_cursor(sf_connection):
    """
    Create a cloned schema for destructive / negative tests, yield a cursor
    that operates inside the clone, and drop the clone on teardown.
    """
    cur = sf_connection.cursor()
    try:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {CLONE_SCHEMA} CLONE {SCHEMA_NAME}")
        cur.execute(f"USE SCHEMA {CLONE_SCHEMA}")
        yield cur
    finally:
        cur.execute(f"DROP SCHEMA IF EXISTS {CLONE_SCHEMA} CASCADE")
        cur.close()


# ---------------------------------------------------------------------------
# Optional Teradata connection fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def td_connection():
    """Return a Teradata connection, or skip if not configured."""
    if not TERADATA_AVAILABLE:
        pytest.skip("Teradata connection not configured")
    import teradatasql  # noqa: F811 — optional dependency

    conn = teradatasql.connect(
        host=TERADATA_CONFIG["host"],
        user=TERADATA_CONFIG["user"],
        password=TERADATA_CONFIG["password"],
        database=TERADATA_CONFIG["database"],
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def td_cursor(td_connection):
    """Return a Teradata cursor for the entire test session."""
    cur = td_connection.cursor()
    yield cur
    cur.close()
