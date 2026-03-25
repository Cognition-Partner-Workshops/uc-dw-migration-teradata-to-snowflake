"""
Shared utility functions for data quality tests.
"""

import datetime
import os
from typing import Any

import pandas as pd


def run_query(cursor, sql: str, params: tuple | None = None) -> list[tuple]:
    """Execute *sql* and return all rows as a list of tuples."""
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor.fetchall()


def run_query_as_dataframe(cursor, sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Execute *sql* and return the result as a Pandas DataFrame."""
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


def assert_row_count(
    cursor,
    table_name: str,
    expected: int,
    tolerance: float = 0.0,
    schema: str | None = None,
) -> int:
    """
    Assert the row count of *table_name* equals *expected* within *tolerance*.
    Returns the actual count.
    """
    qualified = f"{schema}.{table_name}" if schema else table_name
    rows = run_query(cursor, f"SELECT COUNT(*) FROM {qualified}")
    actual = rows[0][0]
    if tolerance > 0:
        lower = expected * (1 - tolerance)
        upper = expected * (1 + tolerance)
        assert lower <= actual <= upper, (
            f"{table_name}: expected ~{expected} (±{tolerance*100:.0f}%), "
            f"got {actual}"
        )
    else:
        assert actual == expected, (
            f"{table_name}: expected {expected}, got {actual}"
        )
    return actual


def compare_dataframes(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    key_columns: list[str],
    tolerance: float = 0.01,
    ignore_columns: list[str] | None = None,
) -> dict[str, Any]:
    """
    Compare two DataFrames row-by-row.

    Returns a dict with keys:
      - match (bool)
      - missing_in_target (DataFrame)
      - missing_in_source (DataFrame)
      - mismatched_rows (DataFrame)
    """
    ignore = set(ignore_columns or [])
    compare_cols = [
        c for c in source_df.columns if c not in ignore and c not in key_columns
    ]

    # Normalise column names to upper
    source_df.columns = [c.upper() for c in source_df.columns]
    target_df.columns = [c.upper() for c in target_df.columns]
    key_columns = [k.upper() for k in key_columns]
    compare_cols = [c.upper() for c in compare_cols]

    merged = source_df.merge(
        target_df,
        on=key_columns,
        how="outer",
        suffixes=("_SRC", "_TGT"),
        indicator=True,
    )

    missing_in_target = merged[merged["_merge"] == "left_only"]
    missing_in_source = merged[merged["_merge"] == "right_only"]
    both = merged[merged["_merge"] == "both"]

    mismatches = []
    for col in compare_cols:
        src_col = f"{col}_SRC"
        tgt_col = f"{col}_TGT"
        if src_col not in both.columns or tgt_col not in both.columns:
            continue
        if both[src_col].dtype in ("float64", "int64") and tolerance > 0:
            diff = (both[src_col] - both[tgt_col]).abs() > tolerance
        else:
            diff = both[src_col].astype(str) != both[tgt_col].astype(str)
        if diff.any():
            mismatches.append(both[diff])

    mismatched_rows = pd.concat(mismatches).drop_duplicates() if mismatches else pd.DataFrame()

    return {
        "match": missing_in_target.empty and missing_in_source.empty and mismatched_rows.empty,
        "missing_in_target": missing_in_target,
        "missing_in_source": missing_in_source,
        "mismatched_rows": mismatched_rows,
    }


def generate_test_report(results: dict[str, dict], output_path: str | None = None) -> str:
    """
    Generate a Markdown test-results report.

    *results* maps category name -> {"passed": int, "failed": int, "details": list[str]}
    Returns the Markdown string and optionally writes to *output_path*.
    """
    lines: list[str] = []
    lines.append("# Data Quality Test Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC")
    lines.append("")

    total_pass = sum(r["passed"] for r in results.values())
    total_fail = sum(r["failed"] for r in results.values())
    lines.append(f"## Summary: {total_pass} passed, {total_fail} failed")
    lines.append("")
    lines.append("| Category | Passed | Failed | Status |")
    lines.append("|----------|--------|--------|--------|")

    for category, data in results.items():
        status = "PASS" if data["failed"] == 0 else "FAIL"
        lines.append(f"| {category} | {data['passed']} | {data['failed']} | {status} |")

    lines.append("")

    # Failure details
    for category, data in results.items():
        if data.get("details"):
            lines.append(f"## {category} — Failure Details")
            lines.append("")
            for detail in data["details"]:
                lines.append(f"- {detail}")
            lines.append("")

    report = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as fh:
            fh.write(report)

    return report
