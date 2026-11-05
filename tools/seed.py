"""Frozen, privacy-masked seed. No network access or wall-clock values."""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-01-31 00:00:00"
OFFICER_FIELDS = {"DIM_ACCOUNT": ("RELATIONSHIP_MGR_ID",), "DIM_BRANCH": ("MANAGER_ID",)}
FILES = {
    "DIM_CUSTOMER": "dim_customer_sample.csv",
    "DIM_ACCOUNT": "dim_account_sample.csv",
    "DIM_PRODUCT": "dim_product_sample.csv",
    "DIM_BRANCH": "dim_branch_sample.csv",
}
KEYS = {
    "DIM_CUSTOMER": "CUSTOMER_ID", "DIM_ACCOUNT": "ACCOUNT_ID", "DIM_PRODUCT": "PRODUCT_ID",
    "DIM_BRANCH": "BRANCH_ID", "DIM_DATE": "DATE_KEY", "FACT_TRANSACTION": "TRANSACTION_ID",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": "SNAPSHOT_MONTH_KEY",
}
RELATIONSHIPS = {
    "DIM_ACCOUNT": (("CUSTOMER_ID", "DIM_CUSTOMER", "CUSTOMER_ID"),
                    ("BRANCH_ID", "DIM_BRANCH", "BRANCH_ID"), ("PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID")),
    "FACT_TRANSACTION": (("ACCOUNT_KEY", "DIM_ACCOUNT", "ACCOUNT_KEY"),
                         ("CUSTOMER_KEY", "DIM_CUSTOMER", "CUSTOMER_KEY"),
                         ("BRANCH_ID", "DIM_BRANCH", "BRANCH_ID"), ("PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID"),
                         ("DATE_KEY", "DIM_DATE", "DATE_KEY")),
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": (("ACCOUNT_KEY", "DIM_ACCOUNT", "ACCOUNT_KEY"),
                                      ("CUSTOMER_KEY", "DIM_CUSTOMER", "CUSTOMER_KEY"),
                                      ("BRANCH_ID", "DIM_BRANCH", "BRANCH_ID"),
                                      ("PRODUCT_ID", "DIM_PRODUCT", "PRODUCT_ID"),
                                      ("SNAPSHOT_DATE", "DIM_DATE", "CALENDAR_DATE")),
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(rows: list[dict]) -> dict:
    ordered = sorted(canonical(row) for row in rows)
    return {"count": len(rows), "sha256": hashlib.sha256("\n".join(ordered).encode()).hexdigest()}


def columns(table: str) -> list[tuple[str, str]]:
    for path in (ROOT / "snowflake/ddl").glob("*.sql"):
        if f"BANKING_DW.{table} (" in path.read_text():
            return [(name, definition.rstrip(",")) for name, definition in
                    re.findall(r"^    (\w+) (.+)$", path.read_text(), re.M)
                    if name not in ("PRIMARY", "FOREIGN", "CONSTRAINT")]
    raise ValueError(table)


def defaults(table: str) -> dict:
    result: dict = {}
    for name, definition in columns(table):
        if "CURRENT_TIMESTAMP" in definition:
            value = STAMP
        elif "DEFAULT" in definition:
            match = re.search(r"DEFAULT\s+(?:'([^']*)'|([\d.]+))", definition)
            value = (match[1] if match[1] is not None else match[2]) if match else None
        else:
            value = None
        result[name] = value
    return result


def mask_officers(table: str, row: dict) -> dict:
    masked = dict(row)
    for name in OFFICER_FIELDS.get(table, ()):
        masked[name] = None
    return masked


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return date(year, n // 31, n % 31 + 1)


def date_rows() -> list[dict]:
    rows = []
    day = date(2000, 1, 1)
    while day < date(2030, 1, 1):
        holiday = {(1, 1): "New Year's Day", (5, 1): "Labour Day", (5, 17): "Constitution Day",
                   (12, 25): "Christmas Day", (12, 26): "Boxing Day"}.get((day.month, day.day))
        offset = (day - easter(day.year)).days
        holiday = {-3: "Maundy Thursday", -2: "Good Friday", 0: "Easter Sunday", 1: "Easter Monday",
                   39: "Ascension Day", 49: "Whit Sunday", 50: "Whit Monday"}.get(offset, holiday)
        quarter = (day.month - 1) // 3 + 1
        end = day.day == calendar.monthrange(day.year, day.month)[1]
        previous = day.replace(year=day.year - 1, day=min(day.day, calendar.monthrange(day.year - 1, day.month)[1]))
        row = {"DATE_KEY": day.strftime("%Y%m%d"), "CALENDAR_DATE": day.isoformat(),
               "DAY_OF_WEEK": str(day.isoweekday()), "DAY_NAME": calendar.day_name[day.weekday()],
               "DAY_OF_MONTH": str(day.day), "DAY_OF_YEAR": str(day.timetuple().tm_yday),
               "WEEK_OF_YEAR": str(day.isocalendar().week), "ISO_WEEK": str(day.isocalendar().week),
               "MONTH_NUM": str(day.month), "MONTH_NAME": calendar.month_name[day.month],
               "MONTH_SHORT": calendar.month_abbr[day.month], "QUARTER_NUM": str(quarter),
               "QUARTER_NAME": f"Q{quarter}", "HALF_YEAR": str((day.month - 1) // 6 + 1),
               "CALENDAR_YEAR": str(day.year), "FISCAL_YEAR": str(day.year), "FISCAL_QUARTER": str(quarter),
               "IS_WEEKEND": str(int(day.weekday() >= 5)), "IS_NORWEGIAN_HOLIDAY": str(int(bool(holiday))),
               "HOLIDAY_NAME": holiday, "IS_BUSINESS_DAY": str(int(day.weekday() < 5 and not holiday)),
               "IS_MONTH_END": str(int(end)), "IS_QUARTER_END": str(int(end and day.month % 3 == 0)),
               "IS_YEAR_END": str(int(end and day.month == 12)), "PRIOR_DAY_DATE": (day - timedelta(days=1)).isoformat(),
               "NEXT_DAY_DATE": (day + timedelta(days=1)).isoformat(), "SAME_DAY_PREV_YEAR": previous.isoformat()}
        rows.append(row)
        day += timedelta(days=1)
    return rows


def exceptions(tables: dict[str, list[dict]]) -> list[dict]:
    output = []
    for table, links in RELATIONSHIPS.items():
        for column, parent, parent_key in links:
            valid = {r[parent_key] for r in tables[parent]}
            for row in tables[table]:
                value = row.get(column)
                if value is not None and value not in valid:
                    output.append({"SOURCE_TABLE": table, "SOURCE_KEY": str(row[KEYS[table]]),
                                   "FK_COLUMN": column, "FK_VALUE": str(value), "REFERENCED_TABLE": parent,
                                   "REASON": "MISSING_PARENT", "ROW_DATA": mask_officers(table, row)})
    return sorted(output, key=canonical)


def build(seed_dir: Path | None = None, *, verify: bool = True) -> dict[str, list[dict]]:
    seed_dir = seed_dir or ROOT / "data/seed"
    manifest = json.loads((ROOT / "snowflake/seed_manifest.json").read_text())
    tables: dict[str, list[dict]] = {}
    for table, filename in FILES.items():
        source = (seed_dir / filename).read_bytes()
        if verify and hashlib.sha256(source).hexdigest() != manifest["source_sha256"][filename]:
            raise ValueError(f"frozen seed changed: {filename}")
        with (seed_dir / filename).open(newline="", encoding="utf-8") as handle:
            raw = list(csv.DictReader(handle, delimiter="|"))
        if any(None in row for row in raw):
            raise ValueError(f"malformed source: {filename}")
        raw.sort(key=lambda row: row[KEYS[table]] if table == "DIM_ACCOUNT" else int(row[KEYS[table]]))
        rows = []
        for index, row in enumerate(raw, 1):
            full = defaults(table)
            if set(row) - set(full):
                raise ValueError(f"unknown source columns: {filename}")
            full.update({k: v or None for k, v in row.items()})
            if table in ("DIM_CUSTOMER", "DIM_ACCOUNT"):
                full[table.removeprefix("DIM_") + "_KEY"] = str(index)
            full["ETL_BATCH_ID"] = "1"
            rows.append(mask_officers(table, full))
        tables[table] = rows
    tables["DIM_DATE"] = date_rows()
    tables["FACT_TRANSACTION"] = []
    tables["FACT_MONTHLY_ACCOUNT_SNAPSHOT"] = []
    tables["SEED_FK_EXCEPTION"] = exceptions(tables)
    return tables
