"""Legacy DDL contracts and engine-neutral, lossless seed fingerprints."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "data/seed/frozen"
EXPECTED = ROOT / "parity/expected/seed.json"
AS_OF = date(2026, 1, 31)
LOAD_TS = datetime(2026, 1, 31, 6)
KEYS = {
    "DIM_CUSTOMER": ["CUSTOMER_KEY"],
    "DIM_ACCOUNT": ["ACCOUNT_KEY"],
    "DIM_PRODUCT": ["PRODUCT_ID"],
    "DIM_BRANCH": ["BRANCH_ID"],
    "DIM_DATE": ["DATE_KEY"],
    "FACT_TRANSACTION": ["TRANSACTION_ID", "ETL_BATCH_ID"],
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": ["ACCOUNT_KEY", "SNAPSHOT_MONTH_KEY"],
    "STG_TRANSACTIONS": ["TRANSACTION_ID"],
    "STG_CUSTOMER": ["CUSTOMER_ID"],
    "STG_TRANSACTION_ERRORS": ["TRANSACTION_ID", "BATCH_ID"],
    "ETL_BATCH_CONTROL": ["BATCH_ID"],
    "ETL_LOG": ["BATCH_ID", "PROCEDURE_NAME", "LOG_LEVEL", "LOG_TS", "LOG_MESSAGE"],
    "DIM_EXCHANGE_RATES": ["FROM_CURRENCY", "TO_CURRENCY", "RATE_DATE"],
}


@dataclass
class Column:
    name: str
    declared_type: str
    nullable: bool


@dataclass
class TableDef:
    name: str
    columns: list[Column]


def tables(directory: Path = ROOT / "ddl/tables") -> dict[str, TableDef]:
    result = {}
    for path in sorted(directory.glob("*.sql")):
        sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", path.read_text(), flags=re.S)
        match = re.search(r"TABLE\s+BANKING_DW\.(\w+)", sql)
        if match is None:
            raise ValueError(f"No table declaration in {path.name}")
        name = match.group(1)
        columns = [
            Column(m[1], m[2], "NOT NULL" not in m[3])
            for m in re.finditer(r"^\s{4}(\w+)\s+([A-Z_]+(?:\([\d,]+\))?)([^\n]*)", sql, re.M)
        ]
        if not columns:
            raise ValueError(f"No columns in {path.name}")
        result[name] = TableDef(name, columns)
    return result


def cast(value: str, declared: str) -> Any:
    if value == r"\N":
        return None
    base = declared.split("(")[0]
    if base in {"INTEGER", "BIGINT", "SMALLINT", "BYTEINT"}:
        return int(value)
    if base == "DECIMAL":
        return Decimal(value)
    if base == "DATE":
        return date.fromisoformat(value)
    if base.startswith("TIMESTAMP"):
        return datetime.fromisoformat(value)
    if base == "TIME":
        return time.fromisoformat(value)
    return value


def read_csv(path: Path, table: TableDef) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="|")
        if reader.fieldnames != [c.name for c in table.columns]:
            raise ValueError(f"Column order mismatch: {table.name}")
        return [{c.name: cast(row[c.name], c.declared_type) for c in table.columns} for row in reader]


def canonical(value: Any, column: Column) -> str | None:
    if value is None:
        return None
    if column.declared_type.startswith("DECIMAL"):
        scale = int(column.declared_type.rstrip(")").split(",")[1])
        return format(Decimal(value).quantize(Decimal(1).scaleb(-scale)), f".{scale}f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, time):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    # Teradata CHAR padding is presentation, not a stored value difference.
    if column.declared_type.startswith("CHAR("):
        return str(value).rstrip(" ")
    return str(value)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def summarize(rows: list[dict[str, Any]], table: TableDef) -> dict[str, Any]:
    profiles = {}
    for col in table.columns:
        values = [r[col.name] for r in rows if r[col.name] is not None]
        normalized = [canonical(v, col) for v in values]
        numeric = col.declared_type.split("(")[0] in {"INTEGER", "BIGINT", "SMALLINT", "BYTEINT", "DECIMAL"}

        # Text extrema are hashed to keep names/addresses out of evidence.
        def extreme(fn: Any) -> Any:
            if not values:
                return None
            v = canonical(fn(values), col)
            return v if numeric or isinstance(values[0], (date, time)) else digest(v)

        profiles[col.name] = {
            "count": len(values),
            "nulls": len(rows) - len(values),
            "distinct": len(set(normalized)),
            "min": extreme(min),
            "max": extreme(max),
            "sum": canonical(sum(values, Decimal(0)), col) if numeric else None,
            "max_length": max((len(v) for v in normalized if v is not None), default=0),
        }
    hashes = {}
    for row in rows:
        key = json.dumps(
            [canonical(row[n], next(c for c in table.columns if c.name == n)) for n in KEYS[table.name]],
            separators=(",", ":"),
        )
        if key in hashes:
            raise ValueError(f"Duplicate comparison key in {table.name}")
        hashes[key] = digest([canonical(row[c.name], c) for c in table.columns])
    return {
        "rows": len(rows),
        "profiles": profiles,
        "key_columns": KEYS[table.name],
        "hashes": hashes,
        "table_sha256": digest(sorted(hashes.items())),
    }


def verify_manifest(directory: Path = FROZEN) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["as_of_date"] != AS_OF.isoformat():
        raise ValueError("Business date changed")
    if set(manifest["tables"]) != set(tables()):
        raise ValueError("Manifest table coverage changed")
    for name, entry in manifest["tables"].items():
        if entry["file"] != name.lower() + ".csv":
            raise ValueError("Unexpected manifest filename")
        if hashlib.sha256((directory / entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Frozen checksum changed: {name}")
    return manifest
