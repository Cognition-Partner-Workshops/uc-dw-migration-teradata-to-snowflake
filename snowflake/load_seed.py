"""JWT-authenticated, internal-stage PUT/COPY seed reset and L1-L4 landing gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bank_model import (
    AS_OF,
    EXPECTED,
    FROZEN,
    KEYS,
    ROOT,
    canonical,
    digest,
    read_csv,
    summarize,
    tables,
    verify_manifest,
)

MARKER = "managed-by=banking-frozen-seed:v1"
REFERENCE = "DERIVED, NOT EXECUTED: no Teradata instance exists."


def connect() -> Any:
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    # This VM can carry a host for a different account. Account is authoritative.
    os.environ.pop("SNOWFLAKE_HOST", None)
    key = serialization.load_pem_private_key(os.environ["SFNFR_PRIVATE_KEY"].encode(), password=None)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tag = dict(
        csid="cs_teradata_banking_seed",
        workload="teradata_banking",
        phase="dev",
        commit=commit,
        run_id="SFNFR_20261104-teradata_banking-dev-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        session_url=os.environ.get(
            "DEVIN_SESSION_URL",
            "https://partner-workshops.devinenterprise.com/sessions/9732580991364f6b9f53feb1bf2fadc2",
        ),
    )
    connection = snowflake.connector.connect(
        account=os.environ["SFNFR_ACCOUNT"],
        user=os.environ["SFNFR_USER"],
        role=os.environ["SFNFR_ROLE"],
        authenticator="SNOWFLAKE_JWT",
        application="Devin_Demo",
        private_key=key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
        session_parameters={
            "QUERY_TAG": json.dumps(tag, separators=(",", ":")),
            "TIMEZONE": "UTC",
            "DATE_OUTPUT_FORMAT": "YYYY-MM-DD",
            "TIMESTAMP_NTZ_OUTPUT_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF6",
        },
    )
    with connection.cursor() as cursor:
        cursor.execute("USE SECONDARY ROLES NONE")
    return connection


def execute_ddl(connection: Any, path: Path) -> None:
    # The checked-in DDL has no semicolons in strings; connector splits SQL correctly.
    with path.open() as stream:
        for cursor in connection.execute_stream(stream):
            cursor.close()


def reset(connection: Any, manifest: dict) -> list[dict]:
    cur = connection.cursor()
    cur.execute(
        "CREATE WAREHOUSE IF NOT EXISTS WH_TD_BANKING WAREHOUSE_SIZE=XSMALL "
        "AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE"
    )
    cur.execute("USE WAREHOUSE WH_TD_BANKING")
    cur.execute("CREATE DATABASE IF NOT EXISTS BANKING_DW")
    cur.execute("USE DATABASE BANKING_DW")
    cur.execute("SHOW SCHEMAS LIKE 'BANKING_DW' IN DATABASE BANKING_DW")
    names = [c.name.lower() for c in cur.description]
    for row in cur.fetchall():
        schema = dict(zip(names, row))
        if schema["name"] == "BANKING_DW" and schema["comment"] != MARKER:
            raise ValueError("Refusing to replace a schema not owned by this fixture loader")
    cur.execute(f"CREATE OR REPLACE SCHEMA BANKING_DW COMMENT='{MARKER}'")
    cur.execute("USE SCHEMA BANKING_DW.BANKING_DW")
    for path in sorted((ROOT / "snowflake/ddl/tables").glob("*.sql")):
        execute_ddl(connection, path)
    cur.execute(
        "CREATE OR REPLACE FILE FORMAT SEED_CSV TYPE=CSV FIELD_DELIMITER='|' "
        "SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"' "
        "NULL_IF=('\\\\N') EMPTY_FIELD_AS_NULL=FALSE ESCAPE_UNENCLOSED_FIELD=NONE "
        "ERROR_ON_COLUMN_COUNT_MISMATCH=TRUE ENCODING='UTF8'"
    )
    cur.execute("CREATE OR REPLACE STAGE SEED_STAGE FILE_FORMAT=SEED_CSV")
    loads = []
    for name, entry in manifest["tables"].items():
        path = (FROZEN / entry["file"]).resolve()
        cur.execute(f"PUT 'file://{path.as_posix()}' @SEED_STAGE/{name}/ AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
        put_id = cur.sfqid
        cur.execute(
            f"COPY INTO BANKING_DW.{name} FROM @SEED_STAGE/{name}/ "
            f"FILES=('{entry['file']}.gz') FILE_FORMAT=(FORMAT_NAME='SEED_CSV') "
            "ON_ERROR=ABORT_STATEMENT FORCE=TRUE"
        )
        copy_id = cur.sfqid
        copied = [dict(zip([c.name.lower() for c in cur.description], row)) for row in cur.fetchall()]
        loaded = sum(int(r.get("rows_loaded", 0)) for r in copied)
        if loaded != entry["rows"] or any(int(r.get("errors_seen", 0)) for r in copied):
            raise ValueError(f"COPY gate failed for {name}")
        loads.append({"table": name, "rows_loaded": loaded, "put_query_id": put_id, "copy_query_id": copy_id})
        print(f"{name}: COPY {loaded} rows")
    for path in sorted((ROOT / "snowflake/ddl/views").glob("*.sql")):
        execute_ddl(connection, path)
    cur.close()
    return loads


def compare(expected: dict, actual: dict) -> dict:
    keys = set(expected["hashes"]) | set(actual["hashes"])
    mismatches = sorted(k for k in keys if expected["hashes"].get(k) != actual["hashes"].get(k))
    profiles = [n for n in expected["profiles"] if expected["profiles"][n] != actual["profiles"].get(n)]
    return {
        "status": "green"
        if not mismatches and not profiles and expected["rows"] == actual["rows"]
        else "red",
        "L1": {
            "expected": expected["rows"],
            "actual": actual["rows"],
            "match": expected["rows"] == actual["rows"],
        },
        "L2": {"match": not profiles, "mismatching_columns": profiles, "actual": actual["profiles"]},
        "L3": {
            "keys": len(keys),
            "matching": len(keys) - len(mismatches),
            "match_percent": round(100 * (len(keys) - len(mismatches)) / len(keys), 6) if keys else 100.0,
            "expected_sha256": expected["table_sha256"],
            "actual_sha256": actual["table_sha256"],
        },
        "L4": [
            {
                "key_sha256": hashlib.sha256(k.encode()).hexdigest(),
                "expected_row_sha256": expected["hashes"].get(k),
                "actual_row_sha256": actual["hashes"].get(k),
            }
            for k in mismatches[:20]
        ],
    }


def verify(connection: Any, manifest: dict) -> tuple[dict, bool]:
    expected = json.loads(EXPECTED.read_text())
    manifest_hash = hashlib.sha256((FROZEN / "manifest.json").read_bytes()).hexdigest()
    if expected["manifest_sha256"] != manifest_hash:
        raise ValueError("Reference belongs to a different frozen manifest")
    report: dict[str, Any] = {
        "reference": REFERENCE,
        "scope": "Seed landing only (not transformed object parity)",
        "as_of_date": AS_OF.isoformat(),
        "manifest_sha256": manifest_hash,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "tables": {},
        "views": {},
        "schema_columns": {},
    }
    cur = connection.cursor()
    cur.execute("USE WAREHOUSE WH_TD_BANKING")
    cur.execute("USE DATABASE BANKING_DW")
    cur.execute("USE SCHEMA BANKING_DW.BANKING_DW")
    cur.execute("SELECT CURRENT_ROLE() = %s", (os.environ["SFNFR_ROLE"],))
    report["supplied_role_verified"] = bool(cur.fetchone()[0])
    for name, table in tables().items():
        cur.execute(f"SELECT * FROM BANKING_DW.{name}")
        columns = [c.name for c in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        actual = summarize(rows, table)
        result = compare(expected["tables"][name], actual)
        if result["L4"]:

            def index(records: list[dict]) -> dict:
                columns_by_name = {c.name: c for c in table.columns}
                return {digest([canonical(r[k], columns_by_name[k]) for k in KEYS[name]]): r for r in records}

            expected_rows = index(read_csv(FROZEN / manifest["tables"][name]["file"], table))
            actual_rows = index(rows)
            for sample in result["L4"]:
                # digest(list) is SHA-256 of the same compact key JSON used in summarize.
                before, after = (
                    expected_rows.get(sample["key_sha256"], {}),
                    actual_rows.get(sample["key_sha256"], {}),
                )
                differences = {}
                for col in table.columns:
                    old, new = canonical(before.get(col.name), col), canonical(after.get(col.name), col)
                    if old != new:
                        text = col.declared_type.startswith(("VARCHAR", "CHAR"))
                        differences[col.name] = dict(
                            expected=digest(old) if text and old is not None else old,
                            actual=digest(new) if text and new is not None else new,
                            representation="sha256" if text else "canonical",
                        )
                sample["columns"] = differences
        result["select_query_id"] = cur.sfqid
        result["manifest_count_match"] = actual["rows"] == manifest["tables"][name]["rows"]
        report["tables"][name] = result
        print(f"{name}: {result['status']}; L1={actual['rows']}; L3={result['L3']['match_percent']}%")
    cur.execute(
        "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH,NUMERIC_PRECISION,"
        "NUMERIC_SCALE,IS_NULLABLE,DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='BANKING_DW' ORDER BY TABLE_NAME,ORDINAL_POSITION"
    )
    for name, column, dtype, length, precision, scale, nullable, dtp in cur.fetchall():
        report["schema_columns"].setdefault(name, []).append(
            dict(
                column=column,
                type=dtype,
                length=length,
                precision=precision,
                scale=scale,
                nullable=nullable,
                datetime_precision=dtp,
            )
        )
    report["schema_contract_errors"] = []
    for name, table in tables().items():
        actual_columns = report["schema_columns"].get(name, [])
        if [c["column"] for c in actual_columns] != [c.name for c in table.columns]:
            report["schema_contract_errors"].append(f"{name}: column order/coverage differs")
            continue
        for column, actual_column in zip(table.columns, actual_columns):
            valid = (actual_column["nullable"] == "YES") == column.nullable
            declared = column.declared_type
            if declared.startswith(("VARCHAR(", "CHAR(")):
                length = int(declared.split("(")[1].rstrip(")"))
                valid = valid and actual_column["type"] == "TEXT" and actual_column["length"] == length
            elif declared.startswith("DECIMAL("):
                precision, scale = map(int, declared.split("(")[1].rstrip(")").split(","))
                valid = (
                    valid
                    and actual_column["type"] == "NUMBER"
                    and actual_column["precision"] == precision
                    and actual_column["scale"] == scale
                )
            elif declared in {"INTEGER", "BIGINT", "SMALLINT", "BYTEINT"}:
                valid = valid and actual_column["type"] == "NUMBER" and actual_column["scale"] == 0
            else:
                valid = (
                    valid
                    and actual_column["type"].replace("_NTZ", "").split("(")[0] == declared.split("(")[0]
                )
            if not valid:
                report["schema_contract_errors"].append(
                    f"{name}.{column.name}: type/length/scale/nullability differs"
                )
    # Read every converted view, not only CREATE: resolves subqueries and executes its plan.
    for name in ["VW_CUSTOMER_360", "VW_REGULATORY_LARGE_TRANSACTIONS", "VW_BRANCH_PERFORMANCE"]:
        cur.execute(f"SELECT COUNT(*) FROM BANKING_DW.{name}")
        report["views"][name] = {
            "compile_and_read": True,
            "rows": cur.fetchone()[0],
            "query_id": cur.sfqid,
            "semantic_parity": "not evaluated in this seed ticket",
        }
    with (ROOT / "data/validation/expected_row_counts.csv").open() as stream:
        counts = list(csv.DictReader(stream, delimiter="|"))
    report["documented_count_gate"] = {
        r["TABLE_NAME"]: report["tables"][r["TABLE_NAME"]]["L1"]["actual"] == int(r["EXPECTED_ROW_COUNT"])
        for r in counts
    }
    good = (
        report["supplied_role_verified"]
        and not report["schema_contract_errors"]
        and all(report["documented_count_gate"].values())
        and all(r["status"] == "green" and r["manifest_count_match"] for r in report["tables"].values())
    )
    report["status"] = "green" if good else "red"
    cur.close()
    return report, good


def write_report(report: dict, label: str) -> None:
    directory = ROOT / "evidence/seed_load"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{label}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        f"# {label}: {report['status'].upper()} — seed landing",
        "",
        f"**{REFERENCE}**",
        "",
        "Business date: 2026-01-31. Live Snowflake PUT/COPY; independent frozen CSV reference.",
        "Scope: 13 seed tables. Views compile/read only; procedures/macros and view semantic parity are not certified.",
        "",
        "| Table | Frozen | Snowflake | L2 | L3 match | L4 sample |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for name, r in report["tables"].items():
        lines.append(
            f"| {name} | {r['L1']['expected']} | {r['L1']['actual']} | "
            f"{'match' if r['L2']['match'] else 'MISMATCH'} | {r['L3']['match_percent']}% | {len(r['L4'])} |"
        )
    lines += [
        "",
        "The JSON includes all column profiles, table fingerprints, query IDs, live schema metadata,",
        "manifest digest and mismatch fingerprints. Text extrema are hashes, never customer details.",
        "Empty error/log tables have 100% vacuous key match. See `parity/expected/DERIVATION.md` for the derivation.",
        f"Live column type/length/scale/nullability gate: {len(report['schema_contract_errors'])} errors.",
        "",
        "## Converted views",
        "",
        *[
            f"- {n}: compiled and read ({r['rows']} rows); semantic parity not evaluated."
            for n, r in report["views"].items()
        ],
        "",
    ]
    (directory / f"{label}.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--recreate", action="store_true", help="Destructively reset only the marked BANKING_DW schema"
    )
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--label", default="load")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.label):
        raise SystemExit("Invalid evidence label")
    logging.disable(logging.CRITICAL)  # connector errors may contain host/account identifiers
    connection = None
    try:
        manifest = verify_manifest()
        connection = connect()
        loads = reset(connection, manifest) if args.recreate else []
        report, good = verify(connection, manifest)
        report["copies"] = loads
        write_report(report, args.label)
        raise SystemExit(0 if good else 1)
    except Exception as error:
        print(
            f"Load failed: {type(error).__name__}; errno={getattr(error, 'errno', None)}; "
            f"query_id={getattr(error, 'sfqid', None)}. No credentials or raw errors logged.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
