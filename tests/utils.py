"""
Utility functions for migration validation tests.

Provides helpers for SQL execution, DataFrame comparison,
row count assertions, and markdown report generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

import pandas as pd


def run_query(cursor: Any, sql: str, params: Optional[Sequence[Any]] = None) -> list[tuple[Any, ...]]:
    """Execute a SQL query and return all rows as a list of tuples.

    Parameters
    ----------
    cursor : database cursor
        A DB-API 2.0 compatible cursor (Snowflake or Teradata).
    sql : str
        The SQL statement to execute.
    params : sequence, optional
        Bind parameters for the query.

    Returns
    -------
    list[tuple]
        Result rows.
    """
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor.fetchall()


def run_query_as_dataframe(cursor: Any, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame:
    """Execute a SQL query and return results as a Pandas DataFrame.

    Parameters
    ----------
    cursor : database cursor
        A DB-API 2.0 compatible cursor.
    sql : str
        The SQL statement to execute.
    params : sequence, optional
        Bind parameters for the query.

    Returns
    -------
    pd.DataFrame
        Query results with column names from cursor.description.
    """
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)

    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


def compare_dataframes(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    key_columns: list[str],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """Compare two DataFrames row-by-row on shared columns.

    Parameters
    ----------
    source_df : pd.DataFrame
        Source (Teradata / seed) data.
    target_df : pd.DataFrame
        Target (Snowflake) data.
    key_columns : list[str]
        Columns to join on.
    tolerance : float
        Acceptable difference for numeric columns.

    Returns
    -------
    dict
        Keys: 'match' (bool), 'missing_in_target', 'extra_in_target',
        'mismatched_rows', 'mismatched_columns'.
    """
    # Normalise column names to uppercase
    source_df.columns = [c.upper() for c in source_df.columns]
    target_df.columns = [c.upper() for c in target_df.columns]
    key_columns = [k.upper() for k in key_columns]

    merged = source_df.merge(target_df, on=key_columns, how="outer", suffixes=("_SRC", "_TGT"), indicator=True)

    missing_in_target = merged[merged["_merge"] == "left_only"]
    extra_in_target = merged[merged["_merge"] == "right_only"]
    both = merged[merged["_merge"] == "both"]

    mismatched_rows: list[dict[str, Any]] = []
    mismatched_columns: set[str] = set()

    common_cols = [c for c in source_df.columns if c not in key_columns and c in target_df.columns]

    for _, row in both.iterrows():
        for col in common_cols:
            src_val = row.get(f"{col}_SRC", row.get(col))
            tgt_val = row.get(f"{col}_TGT", row.get(col))
            if pd.isna(src_val) and pd.isna(tgt_val):
                continue
            if pd.isna(src_val) or pd.isna(tgt_val):
                mismatched_columns.add(col)
                mismatched_rows.append(
                    {k: row.get(k) for k in key_columns} | {"column": col, "source": src_val, "target": tgt_val}
                )
                continue
            # Numeric tolerance check
            try:
                if abs(float(src_val) - float(tgt_val)) > tolerance:
                    mismatched_columns.add(col)
                    mismatched_rows.append(
                        {k: row.get(k) for k in key_columns}
                        | {"column": col, "source": src_val, "target": tgt_val}
                    )
            except (ValueError, TypeError):
                if str(src_val).strip() != str(tgt_val).strip():
                    mismatched_columns.add(col)
                    mismatched_rows.append(
                        {k: row.get(k) for k in key_columns}
                        | {"column": col, "source": src_val, "target": tgt_val}
                    )

    return {
        "match": len(missing_in_target) == 0 and len(extra_in_target) == 0 and len(mismatched_rows) == 0,
        "missing_in_target": missing_in_target[key_columns].to_dict("records") if len(missing_in_target) else [],
        "extra_in_target": extra_in_target[key_columns].to_dict("records") if len(extra_in_target) else [],
        "mismatched_rows": mismatched_rows,
        "mismatched_columns": sorted(mismatched_columns),
    }


def assert_row_count(
    cursor: Any,
    table_name: str,
    expected_count: int,
    tolerance_pct: float = 0.0,
    schema: str = "",
) -> int:
    """Assert that a table's row count matches the expected value.

    Parameters
    ----------
    cursor : database cursor
    table_name : str
    expected_count : int
    tolerance_pct : float
        Allowed percentage variance (e.g. 5.0 for 5%).
    schema : str
        Optional schema qualifier.

    Returns
    -------
    int
        The actual row count.

    Raises
    ------
    AssertionError
        If the actual count is outside the tolerance range.
    """
    qualified = f"{schema}.{table_name}" if schema else table_name
    rows = run_query(cursor, f"SELECT COUNT(*) FROM {qualified}")
    actual = rows[0][0]

    if tolerance_pct > 0:
        lower = expected_count * (1 - tolerance_pct / 100)
        upper = expected_count * (1 + tolerance_pct / 100)
        assert lower <= actual <= upper, (
            f"{table_name}: expected ~{expected_count} (+-{tolerance_pct}%), got {actual}"
        )
    else:
        assert actual == expected_count, (
            f"{table_name}: expected {expected_count}, got {actual}"
        )
    return actual


def generate_test_report(
    results: dict[str, dict[str, Any]],
    output_path: str,
    title: str = "Migration Validation Test Report",
) -> str:
    """Generate a markdown test report from categorised results.

    Parameters
    ----------
    results : dict
        Mapping of category name -> {'passed': int, 'failed': int,
        'skipped': int, 'failures': list[str]}.
    output_path : str
        File path for the generated markdown report.
    title : str
        Report title.

    Returns
    -------
    str
        The output file path.
    """
    lines = [
        f"# {title}",
        "",
        f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Summary",
        "",
        "| Category | Passed | Failed | Skipped |",
        "|----------|--------|--------|---------|",
    ]

    total_passed = total_failed = total_skipped = 0
    for category, data in results.items():
        p = data.get("passed", 0)
        f = data.get("failed", 0)
        s = data.get("skipped", 0)
        total_passed += p
        total_failed += f
        total_skipped += s
        lines.append(f"| {category} | {p} | {f} | {s} |")

    lines.append(f"| **TOTAL** | **{total_passed}** | **{total_failed}** | **{total_skipped}** |")
    lines.append("")

    # Failure details
    has_failures = any(data.get("failures") for data in results.values())
    if has_failures:
        lines.append("## Failure Details")
        lines.append("")
        for category, data in results.items():
            for failure in data.get("failures", []):
                lines.append(f"- **{category}**: {failure}")
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    if total_failed == 0:
        lines.append("All tests passed. Proceed with the next validation phase.")
    else:
        lines.append(
            "Review the failure details above and remediate before "
            "proceeding to data-level validation."
        )
    lines.append("")

    report_text = "\n".join(lines)
    with open(output_path, "w") as fh:
        fh.write(report_text)
    return output_path
