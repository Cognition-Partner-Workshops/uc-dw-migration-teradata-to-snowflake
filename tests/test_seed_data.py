"""Validation tests for the Teradata source warehouse seed data and DDL.

These guard the migration baseline: seed CSVs must match the expected row
counts used for post-migration validation, keys must be unique, foreign keys
must resolve, and every seed column must exist in the corresponding DDL.
"""

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
DDL_DIR = ROOT / "ddl" / "tables"
EXPECTED_COUNTS = ROOT / "data" / "validation" / "expected_row_counts.csv"

SEED_TABLES = {
    "DIM_CUSTOMER": ("dim_customer_sample.csv", "CUSTOMER_ID"),
    "DIM_ACCOUNT": ("dim_account_sample.csv", "ACCOUNT_ID"),
    "DIM_PRODUCT": ("dim_product_sample.csv", "PRODUCT_ID"),
    "DIM_BRANCH": ("dim_branch_sample.csv", "BRANCH_ID"),
}

FOREIGN_KEYS = [
    ("DIM_ACCOUNT", "CUSTOMER_ID", "DIM_CUSTOMER", "CUSTOMER_ID"),
    ("DIM_ACCOUNT", "BRANCH_ID", "DIM_BRANCH", "BRANCH_ID"),
    ("DIM_ACCOUNT", "PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID"),
]


def read_pipe_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def load_seed(table):
    return read_pipe_csv(SEED_DIR / SEED_TABLES[table][0])


def ddl_for(table):
    for path in DDL_DIR.glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        if re.search(rf"\bTABLE\s+(\w+\.)?{table}\b", text, re.IGNORECASE):
            return text
    raise AssertionError(f"No DDL found for {table}")


@pytest.fixture(scope="module")
def expected_counts():
    return {
        row["TABLE_NAME"]: int(row["EXPECTED_ROW_COUNT"])
        for row in read_pipe_csv(EXPECTED_COUNTS)
    }


@pytest.mark.parametrize("table", sorted(SEED_TABLES))
def test_seed_row_count_matches_expected(table, expected_counts):
    assert len(load_seed(table)) == expected_counts[table]


@pytest.mark.parametrize("table", sorted(SEED_TABLES))
def test_seed_primary_key_unique_and_not_null(table):
    key = SEED_TABLES[table][1]
    values = [row[key] for row in load_seed(table)]
    assert all(values), f"{table}.{key} has empty values"
    assert len(values) == len(set(values)), f"{table}.{key} has duplicates"


@pytest.mark.parametrize("child,child_col,parent,parent_col", FOREIGN_KEYS)
def test_seed_foreign_keys_resolve(child, child_col, parent, parent_col):
    parent_keys = {row[parent_col] for row in load_seed(parent)}
    orphans = {row[child_col] for row in load_seed(child)} - parent_keys
    assert not orphans, f"{child}.{child_col} orphans: {sorted(orphans)}"


@pytest.mark.parametrize("table", sorted(SEED_TABLES))
def test_seed_columns_exist_in_ddl(table):
    ddl = ddl_for(table)
    columns = load_seed(table)[0].keys()
    missing = [
        c for c in columns if not re.search(rf"\b{c}\b", ddl, re.IGNORECASE)
    ]
    assert not missing, f"{table} seed columns missing from DDL: {missing}"


@pytest.mark.parametrize("path", sorted(DDL_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_ddl_tables_define_primary_index(path):
    assert re.search(r"PRIMARY\s+INDEX", path.read_text(encoding="utf-8"), re.IGNORECASE)
