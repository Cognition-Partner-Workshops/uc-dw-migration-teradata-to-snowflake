"""Create the one-time frozen input, or verify regeneration without overwriting it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bank_model import AS_OF, FROZEN, LOAD_TS, ROOT, tables
from fixture_data import generate

SEED = 239


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    n = h + correction - 7 * m + 114
    return date(year, n // 31, n % 31 + 1)


def dataset() -> dict[str, list[dict[str, Any]]]:
    data = {k.split(".")[-1]: v for k, v in generate(ROOT / "data/seed", tables(), AS_OF, SEED).items()}
    customers, accounts = data["DIM_CUSTOMER"], data["DIM_ACCOUNT"]
    for row in data["DIM_DATE"]:
        day = row["CALENDAR_DATE"]
        holidays = {
            date(day.year, m, d): label
            for m, d, label in [
                (1, 1, "New Year"),
                (5, 1, "Labour Day"),
                (5, 17, "Constitution Day"),
                (12, 25, "Christmas Day"),
                (12, 26, "Boxing Day"),
            ]
        }
        holidays.update(
            {
                easter(day.year) + timedelta(days=delta): label
                for delta, label in [
                    (-3, "Maundy Thursday"),
                    (-2, "Good Friday"),
                    (0, "Easter Sunday"),
                    (1, "Easter Monday"),
                    (39, "Ascension"),
                    (49, "Whit Sunday"),
                    (50, "Whit Monday"),
                ]
            }
        )
        row.update(
            IS_NORWEGIAN_HOLIDAY=int(day in holidays),
            HOLIDAY_NAME=holidays.get(day),
            IS_BUSINESS_DAY=int(day.isoweekday() < 6 and day not in holidays),
        )
        row["DAY_NAME"] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
            day.weekday()
        ]
        row["MONTH_NAME"] = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ][day.month - 1]
        row["MONTH_SHORT"] = row["MONTH_NAME"][:3]

    new_customer = next(c for c in customers if c["CUSTOMER_ID"] == 1010)
    account = next(a for a in accounts if a["CUSTOMER_ID"] == new_customer["CUSTOMER_ID"])
    staged = []
    scenarios = [("STRUCTURING", "CREDIT", "44000.00", "NOK")] * 3 + [
        ("RAPID_CREDIT", "CREDIT", "100000.00", "NOK"),
        ("RAPID_DEBIT", "DEBIT", "95000.00", "NOK"),
        ("NEW_CUSTOMER_INTL", "TRANSFER", "3000.00", "EUR"),
        ("NEW_CUSTOMER_INTL", "TRANSFER", "3000.00", "EUR"),
        ("TIMESTAMP_TIE", "CREDIT", "100.00", "NOK"),
        ("TIMESTAMP_TIE", "DEBIT", "100.00", "NOK"),
        ("INVALID_ACCOUNT", "DEBIT", "50.00", "NOK"),
        ("INVALID_ACCOUNT", "CREDIT", "75.00", "NOK"),
    ]
    for i, (label, kind, amount, currency) in enumerate(scenarios, 1):
        staged.append(
            dict(
                TRANSACTION_ID=900000 + i,
                ACCOUNT_ID="UNKNOWN_ACCOUNT" if label == "INVALID_ACCOUNT" else account["ACCOUNT_ID"],
                TRANSACTION_DATE=AS_OF,
                TRANSACTION_TIME=time(12, 0, 0) if label == "TIMESTAMP_TIE" else time(8 + i, 0),
                TRANSACTION_TYPE=kind,
                TRANSACTION_SUBTYPE="WIRE_TRANSFER",
                CHANNEL="ONLINE",
                TRANSACTION_AMOUNT=Decimal(amount),
                CURRENCY_CODE=currency,
                MERCHANT_ID=None,
                MERCHANT_NAME=None,
                MERCHANT_CATEGORY=None,
                COUNTERPARTY_ACCT="SYNTHETIC_COUNTERPTY",
                REFERENCE_NUMBER=f"SCENARIO_{i:02}",
                DESCRIPTION_TEXT=label,
                POSTING_DATE=AS_OF,
                VALUE_DATE=AS_OF,
                LOAD_DATE=AS_OF,
            )
        )
    data["STG_TRANSACTIONS"] = staged
    for row, balance in zip(data["FACT_TRANSACTION"][-2:], ["-500.00", "100.00"]):
        row.update(
            ACCOUNT_KEY=account["ACCOUNT_KEY"],
            CUSTOMER_KEY=new_customer["CUSTOMER_KEY"],
            PRODUCT_ID=account["PRODUCT_ID"],
            BRANCH_ID=account["BRANCH_ID"],
            TRANSACTION_DATE=AS_OF,
            TRANSACTION_TIME=time(23, 59),
            TRANSACTION_TS=datetime.combine(AS_OF, time(23, 59)),
            DATE_KEY=20260131,
            RUNNING_BALANCE=Decimal(balance),
        )
    current = {c.name for c in tables()["STG_CUSTOMER"].columns}
    unchanged = {k: v for k, v in customers[0].items() if k in current}
    changed = {k: v for k, v in customers[1].items() if k in current}
    changed.update(RISK_SCORE=Decimal("88.75"), KYC_STATUS="REVIEW", CUSTOMER_SEGMENT="PRIVATE")
    null_change = {k: v for k, v in customers[2].items() if k in current}
    null_change["ADDRESS_LINE_1"] = None
    new_rows = [
        {
            **unchanged,
            "CUSTOMER_ID": n,
            "FIRST_NAME": "Synthetic",
            "LAST_NAME": f"Fixture{n}",
            "EMAIL_ADDRESS": None,
            "PHONE_NUMBER": None,
            "ADDRESS_LINE_1": None,
            "ADDRESS_LINE_2": None,
        }
        for n in [2026001, 2026002]
    ]
    data["STG_CUSTOMER"] = [unchanged, changed, null_change, *new_rows]
    data["STG_TRANSACTION_ERRORS"], data["ETL_LOG"] = [], []
    data["ETL_BATCH_CONTROL"] = [
        dict(
            BATCH_ID=20260130,
            BATCH_DATE=date(2026, 1, 30),
            BATCH_STATUS="COMPLETED",
            START_TS=datetime(2026, 1, 30, 6),
            END_TS=datetime(2026, 1, 30, 7),
        )
    ]
    rates = {
        "NOK": "1.000000",
        "EUR": "11.500123",
        "USD": "10.600005",
        "GBP": "13.400001",
        "SEK": "0.980123",
        "DKK": "1.540001",
    }
    data["DIM_EXCHANGE_RATES"] = [
        dict(FROM_CURRENCY=k, TO_CURRENCY="NOK", RATE_DATE=AS_OF, EXCHANGE_RATE=Decimal(v))
        for k, v in rates.items()
    ]
    return data


def render() -> dict[str, bytes]:
    result = {}
    data = dataset()
    with (ROOT / "data/validation/expected_row_counts.csv").open(newline="") as stream:
        for row in csv.DictReader(stream, delimiter="|"):
            if len(data[row["TABLE_NAME"]]) != int(row["EXPECTED_ROW_COUNT"]):
                raise ValueError("Expected seed count differs: " + row["TABLE_NAME"])
    manifest: dict[str, Any] = {
        "format_version": 1,
        "random_seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "load_timestamp": LOAD_TS.isoformat(sep=" "),
        "null_token": r"\N",
        "tables": {},
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "data/seed").glob("*_sample.csv"))
        },
    }
    for name, table in tables().items():
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="|", lineterminator="\n")
        writer.writerow([c.name for c in table.columns])
        for row in data[name]:
            values = []
            for col in table.columns:
                value = row.get(col.name)
                if value is None and not col.nullable:
                    raise ValueError(f"Missing required field: {name}.{col.name}")
                values.append(r"\N" if value is None else value)
            writer.writerow(values)
        filename = name.lower() + ".csv"
        result[filename] = stream.getvalue().encode("utf-8")
        manifest["tables"][name] = {
            "file": filename,
            "rows": len(data[name]),
            "sha256": hashlib.sha256(result[filename]).hexdigest(),
            "columns": [c.name for c in table.columns],
        }
    result["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FROZEN)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = render()
    if args.check:
        for name, content in files.items():
            if (args.output / name).read_bytes() != content:
                raise SystemExit(f"Non-reproducible frozen input: {name}")
        print("Frozen input regenerates byte-for-byte (13 tables).")
    else:
        if args.output.exists():
            raise SystemExit("Refusing to overwrite frozen input; use --check.")
        args.output.mkdir(parents=True)
        for name, content in files.items():
            (args.output / name).write_bytes(content)
        print("Created frozen input (13 tables). Do not edit it after this step.")


if __name__ == "__main__":
    main()
