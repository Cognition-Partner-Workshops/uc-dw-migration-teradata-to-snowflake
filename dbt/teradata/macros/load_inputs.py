from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT.parents[2]
BASELINE = ROOT / "baseline" / "teradata"
SOURCE_SCHEMA = "td_src_macros"
SOURCE_TABLES = ("DIM_ACCOUNT", "DIM_CUSTOMER", "FACT_TRANSACTION")


def quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def main() -> None:
    database = Path(os.environ.get("TD_DUCKDB_PATH", "target/td.duckdb"))
    database.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BASELINE / "manifest.json").read_text())

    with duckdb.connect(str(database)) as connection:
        connection.execute(f"create schema if not exists {quoted(SOURCE_SCHEMA)}")
        for table in SOURCE_TABLES:
            csv_path = BASELINE / f"{table}.csv"
            with csv_path.open(newline="") as stream:
                columns = next(csv.reader(stream))
            definitions = ", ".join(
                f"{quoted(column)} {manifest[table]['columns'][column]}" for column in columns
            )
            qualified = f"{quoted(SOURCE_SCHEMA)}.{quoted(table)}"
            connection.execute(f"drop table if exists {qualified}")
            connection.execute(f"create table {qualified} ({definitions})")
            connection.execute(
                f"copy {qualified} from ? (header, delimiter ',', nullstr '\\N')",
                [str(csv_path)],
            )
            count = connection.execute(f"select count(*) from {qualified}").fetchone()[0]
            if count != manifest[table]["rows"]:
                raise RuntimeError(f"{table}: loaded {count} rows, expected {manifest[table]['rows']}")
            print(f"Loaded {SOURCE_SCHEMA}.{table}: {count} rows")


if __name__ == "__main__":
    main()
