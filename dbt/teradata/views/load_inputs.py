from __future__ import annotations

import json
import os
import csv
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "baseline" / "teradata"
TABLES = (
    "DIM_CUSTOMER",
    "DIM_ACCOUNT",
    "FACT_TRANSACTION",
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT",
    "DIM_BRANCH",
    "DIM_DATE",
)


def main() -> None:
    database = Path(os.environ.get("TD_DUCKDB_PATH", "target/td.duckdb"))
    database.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BASELINE / "manifest.json").read_text())

    with duckdb.connect(str(database)) as connection:
        connection.execute("create schema if not exists td_src_views")
        for table in TABLES:
            columns = manifest[table]["columns"]
            csv_path = BASELINE / f"{table}.csv"
            with csv_path.open(newline="") as csv_file:
                header = next(csv.reader(csv_file))
            definition = ", ".join(f'"{name}" {columns[name]}' for name in header)
            connection.execute(f'drop table if exists td_src_views."{table}"')
            connection.execute(f'create table td_src_views."{table}" ({definition})')
            connection.execute(
                f'copy td_src_views."{table}" from ? (header, delim \',\', nullstr \'\\N\')',
                [str(csv_path)],
            )
            count = connection.execute(f'select count(*) from td_src_views."{table}"').fetchone()[0]
            print(f"loaded td_src_views.{table}: {count} rows")


if __name__ == "__main__":
    main()
