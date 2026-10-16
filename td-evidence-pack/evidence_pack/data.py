"""Deterministic synthetic banking data, loaded identically into both engines.

Dimensions come from the repo's ``data/seed`` CSVs; facts and history rows are
generated from a fixed random seed so every run is reproducible bit-for-bit.
"""

from __future__ import annotations

import calendar
import csv
import random
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .engines import TableDef

HIGH_DATE = datetime(9999, 12, 31, 23, 59, 59)
LOAD_TS = datetime(2026, 1, 31, 6, 0, 0)
BATCH_ID = 20260131

Row = dict[str, Any]


def _cast(value: str, declared: str) -> Any:
    if value == "":
        return None
    base = declared.split("(")[0].upper()
    if base in {"INTEGER", "INT", "BIGINT", "SMALLINT", "BYTEINT"}:
        return int(value)
    if base in {"DECIMAL", "NUMERIC"}:
        return Decimal(value)
    if base == "DATE":
        return date.fromisoformat(value)
    if base == "TIMESTAMP":
        return datetime.fromisoformat(value)
    return value


def _read_seed(path: Path, table: TableDef) -> list[Row]:
    types = {c.name: c.declared_type for c in table.columns}
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            {k.upper(): _cast(v, types.get(k.upper(), "VARCHAR")) for k, v in rec.items()}
            for rec in csv.DictReader(fh, delimiter="|")
        ]


def _month_ends(start: date, end: date) -> Iterable[date]:
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, calendar.monthrange(y, m)[1])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _money(rng: random.Random, lo: float, hi: float) -> Decimal:
    return Decimal(f"{rng.uniform(lo, hi):.2f}")


def generate(seed_dir: Path, tables: dict[str, TableDef], as_of: date, seed: int = 239) -> dict[str, list[Row]]:
    """Return ``{TABLE_NAME: [row, ...]}`` for the banking DW model."""
    rng = random.Random(seed)
    t = {name.split(".")[-1]: td for name, td in tables.items()}
    audit = {"ETL_BATCH_ID": BATCH_ID, "ETL_INSERT_TS": LOAD_TS, "ETL_UPDATE_TS": LOAD_TS}

    customers = _read_seed(seed_dir / "dim_customer_sample.csv", t["DIM_CUSTOMER"])
    cust_rows: list[Row] = []
    for i, c in enumerate(customers, start=1):
        start = datetime.combine(c["ONBOARDING_DATE"], time())
        cust_rows.append({**c, **audit, "CUSTOMER_KEY": i, "LAST_REVIEW_DATE": as_of - timedelta(days=30 * i),
                          "EFFECTIVE_FROM": start, "EFFECTIVE_TO": HIGH_DATE, "CURRENT_FLAG": "Y"})
    # Closed-out SCD2 history rows: must be excluded by every CURRENT_FLAG = 'Y' filter.
    for offset, src in enumerate(cust_rows[:3], start=1):
        cust_rows.append({**src, "CUSTOMER_KEY": 1000 + offset, "CUSTOMER_SEGMENT": "RETAIL",
                          "RISK_SCORE": Decimal("99.00"), "CURRENT_FLAG": "N",
                          "EFFECTIVE_TO": src["EFFECTIVE_FROM"]})
    cust_key = {r["CUSTOMER_ID"]: r["CUSTOMER_KEY"] for r in cust_rows if r["CURRENT_FLAG"] == "Y"}

    accounts = _read_seed(seed_dir / "dim_account_sample.csv", t["DIM_ACCOUNT"])
    acct_rows: list[Row] = []
    for i, a in enumerate(accounts, start=1):
        acct_rows.append({**a, **audit, "ACCOUNT_KEY": i, "RELATIONSHIP_MGR_ID": 900 + i % 4,
                          "TAX_REPORTING_FLAG": 1, "EFFECTIVE_FROM": datetime.combine(a["OPENING_DATE"], time()),
                          "EFFECTIVE_TO": HIGH_DATE, "CURRENT_FLAG": "Y"})

    products = [{**p, "ETL_BATCH_ID": BATCH_ID, "ETL_INSERT_TS": LOAD_TS}
                for p in _read_seed(seed_dir / "dim_product_sample.csv", t["DIM_PRODUCT"])]
    branches = [{**b, "ETL_BATCH_ID": BATCH_ID, "ETL_INSERT_TS": LOAD_TS,
                 "ADDRESS_LINE_1": f"Gate {b['BRANCH_ID']}", "MANAGER_ID": 500 + b["BRANCH_ID"]}
                for b in _read_seed(seed_dir / "dim_branch_sample.csv", t["DIM_BRANCH"])]
    if branches:
        branches[-1]["IS_ACTIVE"] = 0  # a closed branch must drop out of branch reporting

    dates: list[Row] = []
    d = date(2000, 1, 1)
    while d <= date(2029, 12, 31):
        q = (d.month - 1) // 3 + 1
        last = calendar.monthrange(d.year, d.month)[1]
        dates.append({
            "DATE_KEY": int(d.strftime("%Y%m%d")), "CALENDAR_DATE": d, "DAY_OF_WEEK": d.isoweekday(),
            "DAY_NAME": d.strftime("%A"), "DAY_OF_MONTH": d.day, "DAY_OF_YEAR": d.timetuple().tm_yday,
            "WEEK_OF_YEAR": int(d.strftime("%W")), "ISO_WEEK": d.isocalendar()[1], "MONTH_NUM": d.month,
            "MONTH_NAME": d.strftime("%B"), "MONTH_SHORT": d.strftime("%b"), "QUARTER_NUM": q,
            "QUARTER_NAME": f"Q{q}", "HALF_YEAR": 1 if d.month <= 6 else 2, "CALENDAR_YEAR": d.year,
            "FISCAL_YEAR": d.year, "FISCAL_QUARTER": q, "IS_WEEKEND": int(d.isoweekday() >= 6),
            "IS_NORWEGIAN_HOLIDAY": int((d.month, d.day) in {(1, 1), (5, 1), (5, 17), (12, 25), (12, 26)}),
            "HOLIDAY_NAME": None, "IS_BUSINESS_DAY": int(d.isoweekday() < 6), "IS_MONTH_END": int(d.day == last),
            "IS_QUARTER_END": int(d.day == last and d.month % 3 == 0),
            "IS_YEAR_END": int(d.month == 12 and d.day == 31), "PRIOR_DAY_DATE": d - timedelta(days=1),
            "NEXT_DAY_DATE": d + timedelta(days=1),
            "SAME_DAY_PREV_YEAR": d.replace(year=d.year - 1) if (d.month, d.day) != (2, 29) else None,
        })
        d += timedelta(days=1)

    txns: list[Row] = []
    start = as_of - timedelta(days=730)
    types = ["DEBIT", "CREDIT", "TRANSFER", "FEE", "INTEREST"]
    channels = ["BRANCH", "ATM", "ONLINE", "MOBILE", "POS", "API"]
    currencies = ["NOK", "NOK", "NOK", "EUR", "USD", "GBP", "SEK"]
    fx = {"NOK": Decimal("1"), "EUR": Decimal("11.5"), "USD": Decimal("10.6"), "GBP": Decimal("13.4"),
          "SEK": Decimal("0.98")}
    for txn_id in range(1, 6001):
        acct = rng.choice(acct_rows)
        tdate = start + timedelta(days=rng.randrange(731))
        ts = datetime.combine(tdate, time(rng.randrange(24), rng.randrange(60), rng.randrange(60)))
        roll = rng.random()
        amount = _money(rng, 100_000, 900_000) if roll < 0.03 else _money(rng, 10, 20_000)
        currency = rng.choice(currencies)
        international = int(currency != "NOK")
        if international and roll >= 0.03:
            amount = _money(rng, 2_500, 9_000) if rng.random() < 0.15 else _money(rng, 10, 2_000)
        base_amount = (amount * fx[currency]).quantize(Decimal("0.01"))
        flagged = int(rng.random() < 0.01)
        txns.append({
            "TRANSACTION_ID": txn_id, "TRANSACTION_DATE": tdate, "TRANSACTION_TIME": ts.time(),
            "TRANSACTION_TS": ts, "ACCOUNT_KEY": acct["ACCOUNT_KEY"], "CUSTOMER_KEY": cust_key[acct["CUSTOMER_ID"]],
            "PRODUCT_ID": acct["PRODUCT_ID"], "BRANCH_ID": acct["BRANCH_ID"], "DATE_KEY": int(tdate.strftime("%Y%m%d")),
            "TRANSACTION_TYPE": rng.choice(types), "TRANSACTION_SUBTYPE": "CARD_PAYMENT",
            "CHANNEL": rng.choice(channels), "TRANSACTION_AMOUNT": amount, "TRANSACTION_CURRENCY": currency,
            "BASE_CURRENCY_AMOUNT": base_amount, "EXCHANGE_RATE": fx[currency], "RUNNING_BALANCE": None,
            "MERCHANT_ID": f"M{rng.randrange(1000, 9999)}", "MERCHANT_NAME": f"Merchant {rng.randrange(50)}",
            "MERCHANT_CATEGORY": "5411", "COUNTERPARTY_ACCT": f"NO{rng.randrange(10**9, 10**10)}",
            "REFERENCE_NUMBER": f"REF{txn_id:08d}", "DESCRIPTION_TEXT": "Synthetic transaction",
            "IS_INTERNATIONAL": international, "IS_FLAGGED": flagged,
            "FLAG_REASON": "PATTERN_MATCH" if flagged else None, "POSTING_DATE": tdate, "VALUE_DATE": tdate,
            "ETL_BATCH_ID": BATCH_ID - 1, "ETL_INSERT_TS": LOAD_TS,
        })
    # Restated transactions: same TRANSACTION_ID re-delivered in a later batch. Reports must keep the latest.
    for src in rng.sample([x for x in txns if x["BASE_CURRENCY_AMOUNT"] >= 100_000], 10):
        txns.append({**src, "ETL_BATCH_ID": BATCH_ID, "IS_FLAGGED": 1, "FLAG_REASON": "RESTATED",
                     "BASE_CURRENCY_AMOUNT": src["BASE_CURRENCY_AMOUNT"] + Decimal("1.00")})

    snaps: list[Row] = []
    for acct in acct_rows:
        balance = _money(rng, 1_000, 250_000)
        for me in _month_ends(date(as_of.year - 8, as_of.month + 1 if as_of.month < 12 else 1, 1), as_of):
            debits, credits = _money(rng, 0, 40_000), _money(rng, 0, 40_000)
            closing = balance - debits + credits
            snaps.append({
                "SNAPSHOT_DATE": me, "SNAPSHOT_MONTH_KEY": me.year * 100 + me.month, "ACCOUNT_KEY": acct["ACCOUNT_KEY"],
                "CUSTOMER_KEY": cust_key[acct["CUSTOMER_ID"]], "PRODUCT_ID": acct["PRODUCT_ID"],
                "BRANCH_ID": acct["BRANCH_ID"], "OPENING_BALANCE": balance, "CLOSING_BALANCE": closing,
                "AVERAGE_BALANCE": ((balance + closing) / 2).quantize(Decimal("0.01")),
                "MINIMUM_BALANCE": min(balance, closing), "MAXIMUM_BALANCE": max(balance, closing),
                "TOTAL_DEBITS": debits, "TOTAL_CREDITS": credits, "DEBIT_COUNT": rng.randrange(1, 40),
                "CREDIT_COUNT": rng.randrange(1, 10), "INTEREST_EARNED": _money(rng, 0, 300),
                "INTEREST_CHARGED": _money(rng, 0, 300), "FEES_CHARGED": _money(rng, 0, 150),
                "DAYS_IN_OVERDRAFT": 0, "DAYS_DORMANT": 0, "CURRENCY_CODE": acct["CURRENCY_CODE"],
                "BASE_CURRENCY_CLOSING": closing, "ETL_BATCH_ID": BATCH_ID, "ETL_INSERT_TS": LOAD_TS,
            })
            balance = closing

    return {
        "BANKING_DW.DIM_CUSTOMER": cust_rows, "BANKING_DW.DIM_ACCOUNT": acct_rows,
        "BANKING_DW.DIM_PRODUCT": products, "BANKING_DW.DIM_BRANCH": branches, "BANKING_DW.DIM_DATE": dates,
        "BANKING_DW.FACT_TRANSACTION": txns, "BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT": snaps,
    }


def as_tuples(rows: list[Row], table: TableDef) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Project rows onto the table's column order, failing loudly on missing NOT NULL values."""
    cols = [c.name for c in table.columns]
    required = {c.name for c in table.columns if not c.nullable}
    out = []
    for r in rows:
        missing = [c for c in required if r.get(c) is None]
        if missing:
            raise ValueError(f"{table.name}: missing NOT NULL values for {missing}")
        out.append(tuple(r.get(c) for c in cols))
    return cols, out
