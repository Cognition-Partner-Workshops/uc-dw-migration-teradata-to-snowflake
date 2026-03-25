"""
Category 11: Sample Data Comparison Tests
Test IDs: SD-01 through SD-12

Compares seed CSV data against Snowflake target for dimension tables,
and (when Teradata access is available) performs source-to-target
random-sample comparisons.
"""

import os

import pandas as pd
import pytest

from tests.config import (
    DECIMAL_TOLERANCE,
    SCHEMA_NAME,
    SEED_FILES,
    TERADATA_AVAILABLE,
)
from tests.utils import compare_dataframes, run_query, run_query_as_dataframe


# ---------------------------------------------------------------------------
# Helper: load a pipe-delimited seed CSV
# ---------------------------------------------------------------------------
def _load_seed(table_name: str) -> pd.DataFrame:
    path = SEED_FILES.get(table_name)
    if not path or not os.path.exists(path):
        pytest.skip(f"Seed file not found for {table_name}")
    return pd.read_csv(path, sep="|")


# ---- SD-01 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd01_dim_customer_sample_rows(sf_cursor):
    """SD-01: Compare 3 sample DIM_CUSTOMER rows against seed CSV."""
    seed = _load_seed("DIM_CUSTOMER")
    sample_ids = seed["CUSTOMER_ID"].head(3).tolist()
    placeholders = ", ".join(["%s"] * len(sample_ids))

    df_sf = run_query_as_dataframe(
        sf_cursor,
        f"SELECT CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT "
        f"FROM DIM_CUSTOMER "
        f"WHERE CURRENT_FLAG = 'Y' AND CUSTOMER_ID IN ({placeholders})",
        tuple(sample_ids),
    )
    assert len(df_sf) == 3, f"Expected 3 rows, got {len(df_sf)}"

    for _, row in df_sf.iterrows():
        cid = row["CUSTOMER_ID"]
        seed_row = seed[seed["CUSTOMER_ID"] == cid].iloc[0]
        assert row["FIRST_NAME"] == seed_row["FIRST_NAME"], (
            f"FIRST_NAME mismatch for CUSTOMER_ID {cid}"
        )
        assert row["LAST_NAME"] == seed_row["LAST_NAME"], (
            f"LAST_NAME mismatch for CUSTOMER_ID {cid}"
        )


# ---- SD-02 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd02_dim_account_sample_rows(sf_cursor):
    """SD-02: Compare 3 sample DIM_ACCOUNT rows against seed CSV."""
    seed = _load_seed("DIM_ACCOUNT")
    sample_ids = seed["ACCOUNT_ID"].head(3).tolist()
    placeholders = ", ".join(["%s"] * len(sample_ids))

    df_sf = run_query_as_dataframe(
        sf_cursor,
        f"SELECT ACCOUNT_ID, CUSTOMER_ID, ACCOUNT_TYPE, CURRENCY_CODE "
        f"FROM DIM_ACCOUNT "
        f"WHERE CURRENT_FLAG = 'Y' AND ACCOUNT_ID IN ({placeholders})",
        tuple(sample_ids),
    )
    assert len(df_sf) == 3, f"Expected 3 rows, got {len(df_sf)}"

    for _, row in df_sf.iterrows():
        aid = row["ACCOUNT_ID"]
        seed_row = seed[seed["ACCOUNT_ID"] == aid].iloc[0]
        assert row["ACCOUNT_TYPE"] == seed_row["ACCOUNT_TYPE"], (
            f"ACCOUNT_TYPE mismatch for ACCOUNT_ID {aid}"
        )
        assert row["CURRENCY_CODE"].strip() == seed_row["CURRENCY_CODE"].strip(), (
            f"CURRENCY_CODE mismatch for ACCOUNT_ID {aid}"
        )


# ---- SD-03 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd03_dim_branch_sample_rows(sf_cursor):
    """SD-03: Compare 3 sample DIM_BRANCH rows against seed CSV."""
    seed = _load_seed("DIM_BRANCH")
    sample_ids = seed["BRANCH_ID"].head(3).tolist()
    placeholders = ", ".join(["%s"] * len(sample_ids))

    df_sf = run_query_as_dataframe(
        sf_cursor,
        f"SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, REGION "
        f"FROM DIM_BRANCH WHERE BRANCH_ID IN ({placeholders})",
        tuple(sample_ids),
    )
    assert len(df_sf) == 3, f"Expected 3 rows, got {len(df_sf)}"

    for _, row in df_sf.iterrows():
        bid = row["BRANCH_ID"]
        seed_row = seed[seed["BRANCH_ID"] == bid].iloc[0]
        assert row["BRANCH_NAME"] == seed_row["BRANCH_NAME"], (
            f"BRANCH_NAME mismatch for BRANCH_ID {bid}"
        )
        assert row["REGION"] == seed_row["REGION"], (
            f"REGION mismatch for BRANCH_ID {bid}"
        )


# ---- SD-04 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd04_dim_product_sample_rows(sf_cursor):
    """SD-04: Compare 3 sample DIM_PRODUCT rows against seed CSV."""
    seed = _load_seed("DIM_PRODUCT")
    sample_ids = seed["PRODUCT_ID"].head(3).tolist()
    placeholders = ", ".join(["%s"] * len(sample_ids))

    df_sf = run_query_as_dataframe(
        sf_cursor,
        f"SELECT PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_CATEGORY "
        f"FROM DIM_PRODUCT WHERE PRODUCT_ID IN ({placeholders})",
        tuple(sample_ids),
    )
    assert len(df_sf) == 3, f"Expected 3 rows, got {len(df_sf)}"

    for _, row in df_sf.iterrows():
        pid = row["PRODUCT_ID"]
        seed_row = seed[seed["PRODUCT_ID"] == pid].iloc[0]
        assert row["PRODUCT_NAME"] == seed_row["PRODUCT_NAME"], (
            f"PRODUCT_NAME mismatch for PRODUCT_ID {pid}"
        )


# ---- SD-05 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd05_dim_customer_full_seed_comparison(sf_cursor):
    """SD-05: Full seed comparison — all 15 DIM_CUSTOMER rows."""
    seed = _load_seed("DIM_CUSTOMER")
    df_sf = run_query_as_dataframe(
        sf_cursor,
        "SELECT CUSTOMER_ID, FIRST_NAME, LAST_NAME, GENDER, "
        "       CUSTOMER_SEGMENT, COUNTRY_CODE, IS_ACTIVE "
        "FROM DIM_CUSTOMER WHERE CURRENT_FLAG = 'Y' "
        "ORDER BY CUSTOMER_ID",
    )
    assert len(df_sf) >= len(seed), (
        f"Expected at least {len(seed)} rows, got {len(df_sf)}"
    )

    # Compare common columns
    for _, seed_row in seed.iterrows():
        cid = seed_row["CUSTOMER_ID"]
        sf_row = df_sf[df_sf["CUSTOMER_ID"] == cid]
        assert len(sf_row) == 1, f"CUSTOMER_ID {cid} not found or duplicated"
        sf_row = sf_row.iloc[0]
        assert sf_row["FIRST_NAME"] == seed_row["FIRST_NAME"], f"FIRST_NAME mismatch for {cid}"
        assert sf_row["LAST_NAME"] == seed_row["LAST_NAME"], f"LAST_NAME mismatch for {cid}"


# ---- SD-06 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd06_dim_account_full_seed_comparison(sf_cursor):
    """SD-06: Full seed comparison — all 20 DIM_ACCOUNT rows."""
    seed = _load_seed("DIM_ACCOUNT")
    df_sf = run_query_as_dataframe(
        sf_cursor,
        "SELECT ACCOUNT_ID, CUSTOMER_ID, ACCOUNT_TYPE, CURRENCY_CODE, ACCOUNT_STATUS "
        "FROM DIM_ACCOUNT WHERE CURRENT_FLAG = 'Y' "
        "ORDER BY ACCOUNT_ID",
    )
    assert len(df_sf) >= len(seed), (
        f"Expected at least {len(seed)} rows, got {len(df_sf)}"
    )

    for _, seed_row in seed.iterrows():
        aid = seed_row["ACCOUNT_ID"]
        sf_row = df_sf[df_sf["ACCOUNT_ID"] == aid]
        assert len(sf_row) == 1, f"ACCOUNT_ID {aid} not found or duplicated"
        sf_row = sf_row.iloc[0]
        assert sf_row["ACCOUNT_TYPE"] == seed_row["ACCOUNT_TYPE"], (
            f"ACCOUNT_TYPE mismatch for {aid}"
        )
        assert sf_row["CUSTOMER_ID"] == seed_row["CUSTOMER_ID"], (
            f"CUSTOMER_ID mismatch for {aid}"
        )


# ---- SD-07 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd07_dim_branch_full_seed_comparison(sf_cursor):
    """SD-07: Full seed comparison — all 14 DIM_BRANCH rows."""
    seed = _load_seed("DIM_BRANCH")
    df_sf = run_query_as_dataframe(
        sf_cursor,
        "SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, BRANCH_TYPE, "
        "       CITY, REGION, IS_ACTIVE "
        "FROM DIM_BRANCH ORDER BY BRANCH_ID",
    )
    assert len(df_sf) >= len(seed), (
        f"Expected at least {len(seed)} rows, got {len(df_sf)}"
    )

    for _, seed_row in seed.iterrows():
        bid = seed_row["BRANCH_ID"]
        sf_row = df_sf[df_sf["BRANCH_ID"] == bid]
        assert len(sf_row) == 1, f"BRANCH_ID {bid} not found or duplicated"
        sf_row = sf_row.iloc[0]
        assert sf_row["BRANCH_NAME"] == seed_row["BRANCH_NAME"], (
            f"BRANCH_NAME mismatch for {bid}"
        )
        assert sf_row["REGION"] == seed_row["REGION"], f"REGION mismatch for {bid}"


# ---- SD-08 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd08_dim_product_full_seed_comparison(sf_cursor):
    """SD-08: Full seed comparison — all 10 DIM_PRODUCT rows."""
    seed = _load_seed("DIM_PRODUCT")
    df_sf = run_query_as_dataframe(
        sf_cursor,
        "SELECT PRODUCT_ID, PRODUCT_CODE, PRODUCT_NAME, PRODUCT_CATEGORY, IS_ACTIVE "
        "FROM DIM_PRODUCT ORDER BY PRODUCT_ID",
    )
    assert len(df_sf) >= len(seed), (
        f"Expected at least {len(seed)} rows, got {len(df_sf)}"
    )

    for _, seed_row in seed.iterrows():
        pid = seed_row["PRODUCT_ID"]
        sf_row = df_sf[df_sf["PRODUCT_ID"] == pid]
        assert len(sf_row) == 1, f"PRODUCT_ID {pid} not found or duplicated"
        sf_row = sf_row.iloc[0]
        assert sf_row["PRODUCT_NAME"] == seed_row["PRODUCT_NAME"], (
            f"PRODUCT_NAME mismatch for {pid}"
        )
        assert sf_row["PRODUCT_CATEGORY"] == seed_row["PRODUCT_CATEGORY"], (
            f"PRODUCT_CATEGORY mismatch for {pid}"
        )


# ---- SD-09 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd09_source_to_target_random_customer(sf_cursor, td_cursor):
    """SD-09: Source-to-target random sample — DIM_CUSTOMER (requires Teradata)."""
    if not TERADATA_AVAILABLE:
        pytest.skip("Teradata connection not available — skipping source comparison")

    # Get 5 random CUSTOMER_IDs from Snowflake
    sf_rows = run_query(
        sf_cursor,
        "SELECT CUSTOMER_ID FROM DIM_CUSTOMER "
        "WHERE CURRENT_FLAG = 'Y' "
        "ORDER BY RANDOM() LIMIT 5",
    )
    customer_ids = [r[0] for r in sf_rows]
    placeholders = ", ".join(["?"] * len(customer_ids))

    # Query both systems
    sf_df = run_query_as_dataframe(
        sf_cursor,
        f"SELECT * FROM DIM_CUSTOMER "
        f"WHERE CURRENT_FLAG = 'Y' AND CUSTOMER_ID IN ({', '.join(['%s']*len(customer_ids))})",
        tuple(customer_ids),
    )

    td_df = run_query_as_dataframe(
        td_cursor,
        f"SELECT * FROM BANKING_DW.DIM_CUSTOMER "
        f"WHERE CURRENT_FLAG = 'Y' AND CUSTOMER_ID IN ({placeholders})",
        tuple(customer_ids),
    )

    result = compare_dataframes(
        td_df, sf_df,
        key_columns=["CUSTOMER_ID"],
        tolerance=DECIMAL_TOLERANCE,
        ignore_columns=["CUSTOMER_KEY", "ETL_BATCH_ID", "ETL_INSERT_TS", "ETL_UPDATE_TS"],
    )
    assert result["match"], (
        f"Source-to-target mismatch: "
        f"missing_in_target={len(result['missing_in_target'])}, "
        f"missing_in_source={len(result['missing_in_source'])}, "
        f"mismatched={len(result['mismatched_rows'])}"
    )


# ---- SD-10 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd10_source_to_target_random_transactions(sf_cursor, td_cursor):
    """SD-10: Source-to-target random sample — FACT_TRANSACTION (requires Teradata)."""
    if not TERADATA_AVAILABLE:
        pytest.skip("Teradata connection not available — skipping source comparison")

    sf_rows = run_query(
        sf_cursor,
        "SELECT TRANSACTION_ID FROM FACT_TRANSACTION "
        "ORDER BY RANDOM() LIMIT 20",
    )
    txn_ids = [r[0] for r in sf_rows]
    placeholders_sf = ", ".join(["%s"] * len(txn_ids))
    placeholders_td = ", ".join(["?"] * len(txn_ids))

    sf_df = run_query_as_dataframe(
        sf_cursor,
        f"SELECT TRANSACTION_ID, TRANSACTION_DATE, TRANSACTION_AMOUNT, "
        f"       TRANSACTION_TYPE, CHANNEL "
        f"FROM FACT_TRANSACTION WHERE TRANSACTION_ID IN ({placeholders_sf})",
        tuple(txn_ids),
    )

    td_df = run_query_as_dataframe(
        td_cursor,
        f"SELECT TRANSACTION_ID, TRANSACTION_DATE, TRANSACTION_AMOUNT, "
        f"       TRANSACTION_TYPE, CHANNEL "
        f"FROM BANKING_DW.FACT_TRANSACTION WHERE TRANSACTION_ID IN ({placeholders_td})",
        tuple(txn_ids),
    )

    result = compare_dataframes(
        td_df, sf_df,
        key_columns=["TRANSACTION_ID"],
        tolerance=DECIMAL_TOLERANCE,
    )
    assert result["match"], (
        f"Source-to-target transaction mismatch: "
        f"mismatched={len(result['mismatched_rows'])}"
    )


# ---- SD-11 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd11_source_to_target_norwegian_characters(sf_cursor, td_cursor):
    """SD-11: Source-to-target Norwegian character fidelity (requires Teradata)."""
    if not TERADATA_AVAILABLE:
        pytest.skip("Teradata connection not available — skipping source comparison")

    sf_df = run_query_as_dataframe(
        sf_cursor,
        "SELECT BRANCH_ID, BRANCH_NAME, CITY FROM DIM_BRANCH "
        "WHERE BRANCH_NAME LIKE '%ø%' OR BRANCH_NAME LIKE '%æ%' "
        "   OR BRANCH_NAME LIKE '%å%' "
        "   OR CITY LIKE '%ø%' OR CITY LIKE '%æ%' OR CITY LIKE '%å%'",
    )

    td_df = run_query_as_dataframe(
        td_cursor,
        "SELECT BRANCH_ID, BRANCH_NAME, CITY FROM BANKING_DW.DIM_BRANCH "
        "WHERE BRANCH_NAME LIKE '%ø%' OR BRANCH_NAME LIKE '%æ%' "
        "   OR BRANCH_NAME LIKE '%å%' "
        "   OR CITY LIKE '%ø%' OR CITY LIKE '%æ%' OR CITY LIKE '%å%'",
    )

    result = compare_dataframes(
        td_df, sf_df,
        key_columns=["BRANCH_ID"],
        tolerance=0,
    )
    assert result["match"], "Norwegian character mismatch between source and target"


# ---- SD-12 ----------------------------------------------------------------
@pytest.mark.sample_data
def test_sd12_source_to_target_decimal_precision(sf_cursor, td_cursor):
    """SD-12: Source-to-target DECIMAL precision spot check (requires Teradata)."""
    if not TERADATA_AVAILABLE:
        pytest.skip("Teradata connection not available — skipping source comparison")

    sf_df = run_query_as_dataframe(
        sf_cursor,
        "SELECT TRANSACTION_ID, TRANSACTION_AMOUNT FROM FACT_TRANSACTION "
        "WHERE TRANSACTION_AMOUNT != ROUND(TRANSACTION_AMOUNT, 0) "
        "ORDER BY RANDOM() LIMIT 10",
    )

    txn_ids = sf_df["TRANSACTION_ID"].tolist()
    if not txn_ids:
        pytest.skip("No non-integer TRANSACTION_AMOUNT values to compare")

    placeholders = ", ".join(["?"] * len(txn_ids))
    td_df = run_query_as_dataframe(
        td_cursor,
        f"SELECT TRANSACTION_ID, TRANSACTION_AMOUNT "
        f"FROM BANKING_DW.FACT_TRANSACTION "
        f"WHERE TRANSACTION_ID IN ({placeholders})",
        tuple(txn_ids),
    )

    result = compare_dataframes(
        td_df, sf_df,
        key_columns=["TRANSACTION_ID"],
        tolerance=DECIMAL_TOLERANCE,
    )
    assert result["match"], "DECIMAL precision mismatch between source and target"
