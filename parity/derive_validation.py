"""Derive the Teradata-side expected outputs of data/validation/checksum_queries.sql.

DERIVED, NOT EXECUTED: there is no Teradata instance. Each query is evaluated by hand-written
Python over the frozen seed CSVs, following Teradata (session mode TERA) semantics as documented
in parity/expected/validation/DERIVATION.md. This module reads only the legacy DDL, the frozen
manifest and the frozen CSVs; it never imports the Snowflake connector, the Snowflake ports
under snowflake/validation/ or any harness result.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "snowflake"))

from bank_model import FROZEN, ROOT, read_csv, tables, verify_manifest  # noqa: E402

OUT = ROOT / "parity/expected/validation"
NULL = "\\N"
# Teradata SUM over DECIMAL(n<=15, m) returns DECIMAL(15, m) (MaxDecimal default); overflow is an error.
SUM15_LIMIT = Decimal(10) ** 13


def load() -> dict[str, list[dict[str, Any]]]:
    manifest = verify_manifest()
    defs = tables()
    return {name: read_csv(FROZEN / manifest["tables"][name]["file"], defs[name]) for name in defs}


def td_eq(value: Any, literal: str) -> bool:
    """Teradata-mode comparison: NOT CASESPECIFIC, trailing pad ignored; NULL is unknown (False)."""
    return value is not None and str(value).rstrip(" ").upper() == literal.upper()


def union_label(first: str, label: str) -> str:
    """A UNION column takes the type of its first branch: VARCHAR(len(first)); longer labels truncate."""
    return label[: len(first)]


def money(value: Decimal) -> str:
    if abs(value) >= SUM15_LIMIT:
        raise ValueError("Teradata DECIMAL(15,2) SUM overflow")
    return format(value.quantize(Decimal("0.01")), ".2f")


def hash64(values: list[Any]) -> int:
    text = "\x1f".join(NULL if v is None else str(v) for v in values)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def q1(data: dict) -> tuple[list[str], list[list[Any]]]:
    branches = [
        ("DIM_CUSTOMER", "DIM_CUSTOMER"),
        ("DIM_ACCOUNT", "DIM_ACCOUNT"),
        ("DIM_PRODUCT", "DIM_PRODUCT"),
        ("DIM_BRANCH", "DIM_BRANCH"),
        ("DIM_DATE", "DIM_DATE"),
        ("FACT_TRANSACTION", "FACT_TRANSACTION"),
        ("FACT_MONTHLY_SNAPSHOT", "FACT_MONTHLY_ACCOUNT_SNAPSHOT"),
    ]
    rows = [[union_label(branches[0][0], label), len(data[table])] for label, table in branches]
    return ["TABLE_NAME", "ROW_COUNT"], sorted(rows, key=lambda r: r[0])


def q2(data: dict) -> tuple[list[str], list[list[Any]]]:
    rows = [r for r in data["DIM_CUSTOMER"] if td_eq(r["CURRENT_FLAG"], "Y")]
    columns = ["CUSTOMER_ID", "FIRST_NAME", "LAST_NAME", "CUSTOMER_SEGMENT"]
    dates = [r["ONBOARDING_DATE"] for r in rows if r["ONBOARDING_DATE"] is not None]
    result = [
        len(rows),
        len({r["CUSTOMER_ID"] for r in rows if r["CUSTOMER_ID"] is not None}),
        sum(hash64([r[c] for c in columns]) for r in rows) if rows else None,
        min(dates).isoformat() if dates else None,
        max(dates).isoformat() if dates else None,
        sum(1 for r in rows if r["IS_ACTIVE"] == 1),
    ]
    header = ["ROW_COUNT", "DISTINCT_CUSTOMERS", "HASH_SUM", "MIN_ONBOARD_DATE", "MAX_ONBOARD_DATE"]
    return header + ["ACTIVE_COUNT"], [result]


def q3(data: dict) -> tuple[list[str], list[list[Any]]]:
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in data["FACT_TRANSACTION"]:
        groups[(r["TRANSACTION_DATE"].year, r["TRANSACTION_DATE"].month)].append(r)
    out = []
    for (year, month), rows in sorted(groups.items()):
        base = [r["BASE_CURRENCY_AMOUNT"] for r in rows if r["BASE_CURRENCY_AMOUNT"] is not None]
        out.append(
            [
                year,
                month,
                len(rows),
                money(sum((r["TRANSACTION_AMOUNT"] for r in rows), Decimal(0))),
                money(sum(base, Decimal(0))) if base else None,
                len({r["ACCOUNT_KEY"] for r in rows if r["ACCOUNT_KEY"] is not None}),
                len({r["CUSTOMER_KEY"] for r in rows if r["CUSTOMER_KEY"] is not None}),
                sum(1 for r in rows if td_eq(r["TRANSACTION_TYPE"], "DEBIT")),
                sum(1 for r in rows if td_eq(r["TRANSACTION_TYPE"], "CREDIT")),
                sum(1 for r in rows if r["IS_INTERNATIONAL"] == 1),
            ]
        )
    header = ["TXN_YEAR", "TXN_MONTH", "TXN_COUNT", "TOTAL_AMOUNT", "TOTAL_BASE_AMOUNT", "DISTINCT_ACCOUNTS"]
    return header + ["DISTINCT_CUSTOMERS", "DEBIT_COUNT", "CREDIT_COUNT", "INTL_COUNT"], out


def q4(data: dict) -> tuple[list[str], list[list[Any]]]:
    groups: dict[int, list[dict]] = defaultdict(list)
    for r in data["FACT_MONTHLY_ACCOUNT_SNAPSHOT"]:
        groups[r["SNAPSHOT_MONTH_KEY"]].append(r)
    measures = ["CLOSING_BALANCE", "TOTAL_DEBITS", "TOTAL_CREDITS", "INTEREST_EARNED", "FEES_CHARGED"]
    out = []
    for month, rows in sorted(groups.items()):
        sums = []
        for m in measures:
            values = [r[m] for r in rows if r[m] is not None]
            sums.append(money(sum(values, Decimal(0))) if values else None)
        out.append([month, *sums, len(rows)])
    header = ["SNAPSHOT_MONTH_KEY", "TOTAL_DEPOSITS", "TOTAL_DEBITS", "TOTAL_CREDITS", "TOTAL_INTEREST"]
    return header + ["TOTAL_FEES", "ACCOUNT_COUNT"], out


def not_in_count(rows: list[dict], column: str, keys: list[Any]) -> int:
    """x NOT IN (subquery): unknown (not counted) if x is NULL or the subquery yields any NULL."""
    if any(k is None for k in keys):
        return 0
    allowed = set(keys)
    return sum(1 for r in rows if r[column] is not None and r[column] not in allowed)


def q5(data: dict) -> tuple[list[str], list[list[Any]]]:
    accounts = [r["ACCOUNT_KEY"] for r in data["DIM_ACCOUNT"]]
    customers = [r["CUSTOMER_KEY"] for r in data["DIM_CUSTOMER"]]
    first = "ORPHAN_TXN_ACCOUNT"
    out = [
        [union_label(first, first), not_in_count(data["FACT_TRANSACTION"], "ACCOUNT_KEY", accounts)],
        [
            union_label(first, "ORPHAN_TXN_CUSTOMER"),
            not_in_count(data["FACT_TRANSACTION"], "CUSTOMER_KEY", customers),
        ],
        [
            union_label(first, "ORPHAN_SNAP_ACCOUNT"),
            not_in_count(data["FACT_MONTHLY_ACCOUNT_SNAPSHOT"], "ACCOUNT_KEY", accounts),
        ],
    ]
    return ["CHECK_NAME", "ORPHAN_COUNT"], out


QUERIES = {
    "q1_row_counts": q1,
    "q2_dim_customer_checksum": q2,
    "q3_fact_transaction_aggregates": q3,
    "q4_monthly_balance_reconciliation": q4,
    "q5_orphan_checks": q5,
}


def render(header: list[str], rows: list[list[Any]]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter="|", lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([NULL if v is None else v for v in row])
    return stream.getvalue()


def derive() -> dict[str, str]:
    data = load()
    return {f"{name}.csv": render(*fn(data)) for name, fn in QUERIES.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Prove the checked-in CSVs are reproducible")
    args = parser.parse_args()
    outputs = derive()
    if args.check:
        changed = [n for n, c in outputs.items() if not (OUT / n).exists() or (OUT / n).read_text() != c]
        if changed:
            raise SystemExit(f"Derived validation outputs differ: {changed}; never regenerate to pass a run.")
        print("Derived validation outputs match the frozen seed (no Teradata execution).")
        return
    existing = [n for n in outputs if (OUT / n).exists()]
    if existing:
        raise SystemExit(f"Refusing to overwrite derived outputs {existing}; use --check.")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (OUT / name).write_text(content)
    print("Saved derived validation outputs.")


if __name__ == "__main__":
    main()
