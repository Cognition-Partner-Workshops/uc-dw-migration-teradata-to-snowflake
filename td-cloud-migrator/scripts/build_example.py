"""Build the BANKING_DW example dumps from the repository's Teradata assets.

Writes examples/banking_dw/:
  config_dump.zip      DDL tables/views, macros, procedures, BTEQ scripts (as a client would export them)
  config_dump_dbc.zip  The same tables as a DBC dictionary export (TablesV / ColumnsV / IndicesV CSV)
  data_dump.zip        Seed PSV files, a Parquet file, a split + gzipped fact table and a YAML manifest
Run from td-cloud-migrator/: backend/.venv/bin/python scripts/build_example.py
"""

from __future__ import annotations

import csv
import gzip
import io
import random
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(HERE / "backend"))

from app.td_ddl import parse_ddl  # noqa: E402

OUT = HERE / "examples" / "banking_dw"


def _zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 31, 0, 0, 0)), data)


def config_dump() -> None:
    files = {}
    for d in ("ddl", "dml"):
        for p in sorted((REPO / d).rglob("*")):
            if p.is_file():
                files[f"banking_dw_export/{p.relative_to(REPO).as_posix()}"] = p.read_bytes()
    _zip(OUT / "config_dump.zip", files)


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def dbc_dump() -> None:
    tables, columns, indices = [], [], []
    for p in sorted((REPO / "ddl" / "tables").glob("*.sql")):
        for pt in parse_ddl(p.read_text()):
            t = pt.meta
            tables.append({"DatabaseName": t.database, "TableName": t.name, "TableKind": "T", "PartitioningExpression": t.partition_expression or "", "CommentString": t.comment or "", "RequestText": ""})
            for c in t.columns:
                uni = c.charset == "UNICODE"
                columns.append(
                    {
                        "DatabaseName": t.database, "TableName": t.name, "ColumnName": c.name, "ColumnId": 1024 + c.ordinal,
                        "ColumnType": c.td_type_code, "ColumnLength": (c.length or 0) * (2 if uni else 1) or "",
                        "DecimalTotalDigits": c.precision if c.precision is not None else "",
                        "DecimalFractionalDigits": c.scale if c.scale is not None else (c.fractional_seconds if c.fractional_seconds is not None else ""),
                        "CharType": (2 if uni else 1) if c.charset else "", "UpperCaseFlag": "C" if c.case_specific else "N",
                        "Nullable": "Y" if c.nullable else "N", "DefaultValue": c.default or "",
                        "IdColType": ("GA" if c.identity.always else "GD") if c.identity else "", "ColumnFormat": c.format or "",
                        "CommentString": c.comment or "",
                    }
                )  # fmt: skip
            for pos, col in enumerate(t.primary_index, 1):
                indices.append({"DatabaseName": t.database, "TableName": t.name, "IndexNumber": 1, "IndexType": "Q" if t.partition_expression else "P", "UniqueFlag": "Y" if t.primary_index_unique else "N", "ColumnName": col, "ColumnPosition": pos})
            for n, cols in enumerate(t.secondary_indexes, 1):
                for pos, col in enumerate(cols, 1):
                    indices.append({"DatabaseName": t.database, "TableName": t.name, "IndexNumber": 4 * n, "IndexType": "S", "UniqueFlag": "N", "ColumnName": col, "ColumnPosition": pos})
    for p in sorted((REPO / "ddl" / "views").glob("*.sql")):
        name = p.stem.split("_", 1)[1].upper()
        tables.append({"DatabaseName": "BANKING_DW", "TableName": name, "TableKind": "V", "PartitioningExpression": "", "CommentString": "", "RequestText": p.read_text()})
    _zip(OUT / "config_dump_dbc.zip", {"dbc/TablesV.csv": _csv(tables), "dbc/ColumnsV.csv": _csv(columns), "dbc/IndicesV.csv": _csv(indices)})


def dim_date() -> bytes:
    start = date(2024, 1, 1)
    days = [start + timedelta(days=i) for i in range(731)]
    cols: dict[str, list] = {k: [] for k in ("DATE_KEY", "CALENDAR_DATE", "DAY_OF_WEEK", "DAY_NAME", "DAY_OF_MONTH", "DAY_OF_YEAR", "WEEK_OF_YEAR", "ISO_WEEK", "MONTH_NUM", "MONTH_NAME", "MONTH_SHORT", "QUARTER_NUM", "QUARTER_NAME", "HALF_YEAR", "CALENDAR_YEAR", "FISCAL_YEAR", "FISCAL_QUARTER", "IS_WEEKEND", "IS_BUSINESS_DAY", "IS_MONTH_END", "IS_QUARTER_END", "IS_YEAR_END", "PRIOR_DAY_DATE", "NEXT_DAY_DATE")}
    for d in days:
        nxt = d + timedelta(days=1)
        q = (d.month - 1) // 3 + 1
        vals = [int(d.strftime("%Y%m%d")), d, d.isoweekday(), d.strftime("%A"), d.day, d.timetuple().tm_yday, int(d.strftime("%U")), d.isocalendar()[1], d.month, d.strftime("%B"), d.strftime("%b"), q, f"Q{q}", 1 if d.month <= 6 else 2, d.year, d.year, q, int(d.isoweekday() >= 6), int(d.isoweekday() < 6), int(nxt.month != d.month), int(nxt.month != d.month and d.month % 3 == 0), int(d.month == 12 and d.day == 31), d - timedelta(days=1), nxt]
        for k, v in zip(cols, vals):
            cols[k].append(v)
    types = {"CALENDAR_DATE": pa.date32(), "PRIOR_DAY_DATE": pa.date32(), "NEXT_DAY_DATE": pa.date32(), "DAY_NAME": pa.string(), "MONTH_NAME": pa.string(), "MONTH_SHORT": pa.string(), "QUARTER_NAME": pa.string()}
    table = pa.table({k: pa.array(v, type=types.get(k, pa.int32())) for k, v in cols.items()})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


FACT_COLS = ["TRANSACTION_ID", "TRANSACTION_DATE", "TRANSACTION_TS", "ACCOUNT_KEY", "CUSTOMER_KEY", "PRODUCT_ID", "BRANCH_ID", "DATE_KEY", "TRANSACTION_TYPE", "CHANNEL", "TRANSACTION_AMOUNT", "TRANSACTION_CURRENCY", "BASE_CURRENCY_AMOUNT", "MERCHANT_NAME", "IS_INTERNATIONAL", "IS_FLAGGED", "SOURCE_SYSTEM"]


def fact_rows() -> list[list[str]]:
    rnd = random.Random(42)
    rows = []
    for i in range(1, 601):
        d = date(2025, 1, 1) + timedelta(days=rnd.randrange(365))
        ts = datetime(d.year, d.month, d.day, rnd.randrange(24), rnd.randrange(60), rnd.randrange(60))
        amt = round(rnd.uniform(5, 150000 if i % 50 == 0 else 5000), 2)
        intl = int(rnd.random() < 0.1)
        rows.append([str(9000000 + i), d.isoformat(), ts.isoformat(sep=" "), str(rnd.randint(1, 20)), str(rnd.randint(1, 15)), str(rnd.randint(1, 10)), str(rnd.choice(range(101, 115))), d.strftime("%Y%m%d"), rnd.choice(["DEBIT", "CREDIT", "TRANSFER", "FEE"]), rnd.choice(["ONLINE", "MOBILE", "BRANCH", "ATM"]), f"{amt:.2f}", "EUR" if intl else "NOK", f"{amt * (11.5 if intl else 1):.2f}", rnd.choice(["REMA 1000", "Kiwi", "Vinmonopolet", "Ruter", "", "SAS"]), str(intl), str(int(amt > 100000)), "CORE_BANKING"])
    rows[17][1] = "2025-02-30"  # invalid date -> rejected
    rows[333][3] = ""  # NULL in NOT NULL ACCOUNT_KEY -> rejected
    rows[480][10] = "12,50.00x"  # bad decimal -> rejected
    return rows


def data_dump() -> None:
    files: dict[str, bytes] = {}
    for p in sorted((REPO / "data" / "seed").glob("*.csv")):
        files[f"extract/dims/{p.name}"] = p.read_bytes()
    files["extract/dims/dim_date_2024_2025.parquet"] = dim_date()
    rows = fact_rows()
    part1 = "\n".join("|".join(r) for r in [FACT_COLS] + rows[:300]) + "\n"
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows[300:])
    files["extract/facts/txn_2025_part1.psv"] = part1.encode()
    files["extract/facts/txn_2025_part2.csv.gz"] = gzip.compress(buf.getvalue().encode(), mtime=0)
    files["extract/manifest.yaml"] = (
        "# Table-to-file mapping supplied with the extract\n"
        "tables:\n"
        "  - table: BANKING_DW.DIM_DATE\n    files: [dim_date_2024_2025.parquet]\n"
        "  - table: BANKING_DW.FACT_TRANSACTION\n    files:\n"
        "      - {file: txn_2025_part1.psv, delimiter: '|', header: true}\n"
        "      - {file: txn_2025_part2.csv.gz, delimiter: ',', header: false}\n"
    ).encode()
    _zip(OUT / "data_dump.zip", files)



if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    config_dump()
    dbc_dump()
    data_dump()
    print("\n".join(f"{p.name}: {p.stat().st_size} bytes" for p in sorted(OUT.glob("*.zip"))))
