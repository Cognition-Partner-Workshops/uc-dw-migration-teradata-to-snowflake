"""
Utility helpers for migration data-quality tests.

Functions for query execution, dataframe comparison, assertions,
and markdown report generation.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from tests.config import DECIMAL_TOLERANCE, SNOWFLAKE_SCHEMA


# ---------------------------------------------------------------------------
# Query execution helpers
# ---------------------------------------------------------------------------

def run_query(cursor, sql: str, params: Optional[Tuple] = None) -> List[Tuple]:
    """Execute *sql* and return all rows as a list of tuples."""
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor.fetchall()


def run_query_as_dataframe(cursor, sql: str, params: Optional[Tuple] = None) -> pd.DataFrame:
    """Execute *sql* and return the result as a Pandas DataFrame."""
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


def run_scalar(cursor, sql: str, params: Optional[Tuple] = None) -> Any:
    """Execute *sql* and return the single scalar value."""
    rows = run_query(cursor, sql, params)
    if rows and rows[0]:
        return rows[0][0]
    return None


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_row_count(
    cursor,
    table_name: str,
    expected: int,
    tolerance_pct: float = 0.0,
    schema: Optional[str] = None,
) -> int:
    """Assert that *table_name* has approximately *expected* rows.

    Parameters
    ----------
    tolerance_pct : float
        Allowed percentage deviation (e.g. 5.0 means ±5 %).
        Use 0.0 for exact match.

    Returns the actual count.
    """
    schema = schema or SNOWFLAKE_SCHEMA
    actual = run_scalar(cursor, f"SELECT COUNT(*) FROM {schema}.{table_name}")
    if tolerance_pct == 0.0:
        assert actual == expected, (
            f"{table_name}: expected exactly {expected} rows, got {actual}"
        )
    else:
        lower = expected * (1 - tolerance_pct / 100)
        upper = expected * (1 + tolerance_pct / 100)
        assert lower <= actual <= upper, (
            f"{table_name}: expected {expected} ± {tolerance_pct}% "
            f"(range [{lower:.0f}, {upper:.0f}]), got {actual}"
        )
    return actual


def assert_no_duplicates(cursor, table_name: str, key_column: str, schema: Optional[str] = None) -> None:
    """Assert zero duplicate values in *key_column* of *table_name*."""
    schema = schema or SNOWFLAKE_SCHEMA
    sql = f"""
        SELECT {key_column}, COUNT(*) AS cnt
        FROM {schema}.{table_name}
        GROUP BY {key_column}
        HAVING COUNT(*) > 1
    """
    dupes = run_query(cursor, sql)
    assert len(dupes) == 0, (
        f"{table_name}.{key_column}: found {len(dupes)} duplicate key(s) — "
        f"first few: {dupes[:5]}"
    )


def assert_no_orphans(
    cursor,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
    allow_null: bool = False,
    schema: Optional[str] = None,
) -> int:
    """Assert that every *child_column* value exists in *parent_column*.

    Returns the orphan count (should be 0).
    """
    schema = schema or SNOWFLAKE_SCHEMA
    null_filter = f"AND c.{child_column} IS NOT NULL" if allow_null else ""
    sql = f"""
        SELECT COUNT(*)
        FROM {schema}.{child_table} c
        WHERE c.{child_column} NOT IN (
            SELECT {parent_column} FROM {schema}.{parent_table}
        )
        {null_filter}
    """
    count = run_scalar(cursor, sql)
    assert count == 0, (
        f"Referential integrity violation: {child_table}.{child_column} -> "
        f"{parent_table}.{parent_column}: {count} orphan(s)"
    )
    return count


# ---------------------------------------------------------------------------
# DataFrame comparison
# ---------------------------------------------------------------------------

def compare_dataframes(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    key_columns: List[str],
    tolerance: float = DECIMAL_TOLERANCE,
) -> Dict[str, Any]:
    """Compare two DataFrames row-by-row on *key_columns*.

    Returns a dict with keys:
        matched       – number of fully matched rows
        mismatched    – list of dicts describing mismatches
        missing_in_target – keys present in source but not target
        extra_in_target   – keys present in target but not source
    """
    # Normalise column names to upper case
    source_df.columns = [c.upper() for c in source_df.columns]
    target_df.columns = [c.upper() for c in target_df.columns]
    key_columns = [k.upper() for k in key_columns]

    source_df = source_df.set_index(key_columns)
    target_df = target_df.set_index(key_columns)

    common_idx = source_df.index.intersection(target_df.index)
    missing_in_target = source_df.index.difference(target_df.index).tolist()
    extra_in_target = target_df.index.difference(source_df.index).tolist()

    mismatches: List[Dict[str, Any]] = []
    for idx in common_idx:
        src_row = source_df.loc[idx]
        tgt_row = target_df.loc[idx]
        for col in source_df.columns:
            if col not in target_df.columns:
                continue
            sv = src_row[col] if not isinstance(src_row, pd.DataFrame) else src_row[col].iloc[0]
            tv = tgt_row[col] if not isinstance(tgt_row, pd.DataFrame) else tgt_row[col].iloc[0]
            if pd.isna(sv) and pd.isna(tv):
                continue
            if pd.isna(sv) or pd.isna(tv):
                mismatches.append({"key": idx, "column": col, "source": sv, "target": tv})
                continue
            try:
                if abs(float(sv) - float(tv)) > tolerance:
                    mismatches.append({"key": idx, "column": col, "source": sv, "target": tv})
            except (TypeError, ValueError):
                if str(sv).strip().upper() != str(tv).strip().upper():
                    mismatches.append({"key": idx, "column": col, "source": sv, "target": tv})

    return {
        "matched": len(common_idx) - len({m["key"] for m in mismatches}),
        "mismatched": mismatches,
        "missing_in_target": missing_in_target,
        "extra_in_target": extra_in_target,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_test_report(
    results: Dict[str, Dict[str, int]],
    output_path: Optional[str] = None,
    performance_baselines: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate a Markdown test-results summary.

    Parameters
    ----------
    results : dict
        Mapping of category name -> {"passed": n, "failed": n, "skipped": n, "details": [...]}.
    output_path : str, optional
        If provided, write the report to this file.
    performance_baselines : list, optional
        List of dicts with query name and execution time.

    Returns the report as a string.
    """
    lines: List[str] = []
    lines.append("# Data Quality Test Report")
    lines.append(f"\n**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")

    total_pass = sum(r.get("passed", 0) for r in results.values())
    total_fail = sum(r.get("failed", 0) for r in results.values())
    total_skip = sum(r.get("skipped", 0) for r in results.values())

    lines.append("## Summary\n")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------||")
    lines.append(f"| Passed | {total_pass} |")
    lines.append(f"| Failed | {total_fail} |")
    lines.append(f"| Skipped | {total_skip} |")
    lines.append(f"| **Total** | **{total_pass + total_fail + total_skip}** |")

    lines.append("\n## Results by Category\n")
    lines.append("| Category | Passed | Failed | Skipped |")
    lines.append("|----------|--------|--------|---------|")
    for cat, counts in results.items():
        lines.append(
            f"| {cat} | {counts.get('passed', 0)} | {counts.get('failed', 0)} | {counts.get('skipped', 0)} |"
        )

    # Failure details
    any_failures = any(r.get("details") for r in results.values())
    if any_failures:
        lines.append("\n## Failure Details\n")
        for cat, counts in results.items():
            details = counts.get("details", [])
            if details:
                lines.append(f"### {cat}\n")
                for d in details:
                    lines.append(f"- **{d.get('test', 'unknown')}**: {d.get('message', '')}")
                lines.append("")

    # Performance baselines
    if performance_baselines:
        lines.append("\n## Performance Baselines\n")
        lines.append("| Query | Execution Time (s) |")
        lines.append("|-------|--------------------|")
        for pb in performance_baselines:
            lines.append(f"| {pb['name']} | {pb['time_seconds']:.2f} |")

    lines.append("\n## Recommendations\n")
    if total_fail > 0:
        lines.append("- Investigate and resolve all failing tests before go-live.")
        lines.append("- Re-run failed categories in isolation for detailed diagnostics.")
    else:
        lines.append("- All tests passed. Proceed with UAT sign-off.")
    lines.append("- Run negative tests (Category 7) in a cloned schema for isolation.")
    lines.append("- Capture performance baselines for the 3 most complex queries.")

    report = "\n".join(lines) + "\n"
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
    return report
