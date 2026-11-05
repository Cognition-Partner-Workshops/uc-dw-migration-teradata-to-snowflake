"""Guarded EXT-only schema/seed verification, with evidence kept outside Git."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from tools import seed
from tools import sf_attribution as sf

EP = sf.endpoint("cs_mig_td_schema_seed")
SCOPE = f"mig_td_schema_seed_{sf.RUN_TOKEN.lower()}"
DATABASE = sf.database_name(SCOPE)
WAREHOUSE = sf.warehouse_name(SCOPE)
MONITOR = sf.resource_monitor_name("mig_td_schema")
SCHEMA = "BANKING_DW"
LOAD_ORDER = ("DIM_PRODUCT", "DIM_BRANCH", "DIM_CUSTOMER", "DIM_DATE", "DIM_ACCOUNT",
              "FACT_TRANSACTION", "FACT_MONTHLY_ACCOUNT_SNAPSHOT", "SEED_FK_EXCEPTION")


def connection_parameters(env: dict, commit: str) -> dict:
    from cryptography.hazmat.primitives import serialization

    if date.today() > date.fromisoformat(sf.EXPIRES):
        raise ValueError("EXT credentials and objects have expired")
    account = env["SNOWFLAKE_EXT_ACCOUNT"]
    if "yd76133" in account.lower():
        raise ValueError("forbidden account")
    pem = env["SNOWFLAKE_EXT_PRIVATE_KEY"].replace("\\n", "\n").encode()
    key = serialization.load_pem_private_key(pem, password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    params = sf.connection_params(EP, phase="dev", account=account, private_key=der,
                                  commit=commit, run_id=sf.make_run_id(EP.workload, "dev"),
                                  session_url=env["DEVIN_SESSION_URL"], role="DEVIN_EXT_ROLE")
    params["user"] = env["SNOWFLAKE_EXT_USER"]
    for name in ("warehouse", "database", "schema"):
        params.pop(name)
    params["session_parameters"].update({"TIMEZONE": "UTC", "STATEMENT_TIMEOUT_IN_SECONDS": 120,
                                         "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 60,
                                         "TIMESTAMP_NTZ_OUTPUT_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF6"})
    return params


class Runner:
    def __init__(self, connection):
        self.connection = connection
        self.evidence: dict = {"queries": [], "application": sf.APPLICATION,
                               "application_registration": sf.APPLICATION_REGISTRATION,
                               "database": DATABASE, "warehouse": WAREHOUSE, "monitor": MONITOR}

    def execute(self, label: str, sql: str, params=None):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
        except Exception:
            cursor.close()
            raise
        self.evidence["queries"].append({"label": label, "query_id": cursor.sfqid})
        return cursor

    def command(self, label: str, sql: str, params=None):
        with self.execute(label, sql, params):
            pass

    def show(self, label: str, sql: str) -> list[dict]:
        with self.execute(label, sql) as cursor:
            names = [d[0].lower() for d in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def guard(self):
        monitors = self.show("monitor_read_back", f"SHOW RESOURCE MONITORS LIKE '{MONITOR}'")
        exact = [r for r in monitors if r["name"] == MONITOR]
        if len(exact) != 1:
            raise RuntimeError(f"required monitor not visible: {MONITOR}; no compute started")
        monitor = exact[0]
        self.evidence["monitor_read_back"] = monitor
        if (float(monitor["credit_quota"] or 0) <= 0 or
                str(monitor.get("frequency", "")).upper() != "MONTHLY" or
                not monitor.get("suspend_at") or not monitor.get("suspend_immediately_at")):
            raise RuntimeError("monitor needs a positive monthly quota and suspend triggers")
        warehouses = self.show("warehouse_read_back", f"SHOW WAREHOUSES LIKE '{WAREHOUSE}'")
        exact = [r for r in warehouses if r["name"] == WAREHOUSE]
        if len(exact) != 1 or exact[0].get("resource_monitor") != MONITOR:
            raise RuntimeError(f"ACCOUNTADMIN must attach {MONITOR} to {WAREHOUSE}; no compute started")
        wh = exact[0]
        if (wh["size"].upper().replace("-", "") != "XSMALL" or int(wh["auto_suspend"]) > 60 or
                int(wh["auto_suspend"]) <= 0 or int(wh.get("max_cluster_count", 1)) != 1):
            raise RuntimeError("warehouse must be single-cluster XSMALL with auto_suspend <= 60")
        self.evidence["warehouse_read_back"] = wh

    def deploy(self):
        comment = sf.sql_string(sf.external_comment(csid=EP.csid, purpose="frozen migration seed"))
        self.command("create_database", f"CREATE DATABASE IF NOT EXISTS {DATABASE} COMMENT = {comment}")
        self.command("create_schema", f"CREATE SCHEMA IF NOT EXISTS {DATABASE}.{SCHEMA} COMMENT = {comment}")
        self.command("use_database", f"USE DATABASE {DATABASE}")
        self.command("use_schema", f"USE SCHEMA {SCHEMA}")
        from snowflake.connector.util_text import split_statements
        from io import StringIO

        paths = {p.name.split('_', 1)[1].removesuffix('.sql').upper(): p
                 for p in (seed.ROOT / "snowflake/ddl").glob("*.sql")}
        paths["FACT_MONTHLY_ACCOUNT_SNAPSHOT"] = paths.pop("FACT_MONTHLY_SNAPSHOT")
        for table in LOAD_ORDER:
            for sql, _ in split_statements(StringIO(paths[table].read_text())):
                self.command(f"ddl:{table}", sql)

    def load(self, tables: dict[str, list[dict]], iteration: int):
        self.command(f"begin:{iteration}", "BEGIN")
        try:
            for table in reversed(LOAD_ORDER):
                self.command(f"delete:{iteration}:{table}", f"DELETE FROM {SCHEMA}.{table}")
            for table in LOAD_ORDER:
                rows = tables[table]
                if not rows:
                    continue
                names = list(rows[0])
                width = len(names)
                expressions = [f"column{i + 1}" for i in range(width)]
                if table == "SEED_FK_EXCEPTION":
                    expressions[names.index("ROW_DATA")] = f"PARSE_JSON(column{names.index('ROW_DATA') + 1})"
                for offset in range(0, len(rows), 250):
                    batch = rows[offset:offset + 250]
                    placeholders = ",".join("(" + ",".join(["%s"] * width) + ")" for _ in batch)
                    values = [seed.canonical(row[name]) if isinstance(row[name], dict) else row[name]
                              for row in batch for name in names]
                    sql = (f"INSERT INTO {SCHEMA}.{table} ({','.join(names)}) "
                           f"SELECT {','.join(expressions)} FROM VALUES {placeholders}")
                    self.command(f"seed_load:{iteration}:{table}:{offset}", sql, values)
            self.command(f"commit:{iteration}", "COMMIT")
        except Exception:
            self.command(f"rollback:{iteration}", "ROLLBACK")
            raise

    def snapshot(self, iteration: int) -> dict:
        result = {}
        for table in LOAD_ORDER:
            with self.execute(f"hash:{iteration}:{table}",
                              f"SELECT COUNT(*), HASH_AGG(*) FROM {SCHEMA}.{table}") as cursor:
                count, checksum = cursor.fetchone()
                result[table] = {"count": count, "hash_agg": checksum}
        return result

    def verify(self, tables: dict[str, list[dict]]):
        self.guard()
        active = False
        try:
            self.deploy()
            self.command("use_warehouse", f"USE WAREHOUSE {WAREHOUSE}")
            active = True
            self.load(tables, 1)
            first = self.snapshot(1)
            self.load(tables, 2)
            second = self.snapshot(2)
            self.evidence.update({"first": first, "second": second, "repeat_equal": first == second,
                                  "frozen_input": {t: seed.fingerprint(r) for t, r in tables.items()}})
            if first != second:
                raise AssertionError("repeat seed counts or hashes differ")
            for table, rows in tables.items():
                if first[table]["count"] != len(rows):
                    raise AssertionError(f"seed row count differs: {table}")
            for table, fields in seed.OFFICER_FIELDS.items():
                for field in fields:
                    with self.execute(f"officer_mask:{table}:{field}",
                                      f"SELECT COUNT(*) FROM {SCHEMA}.{table} WHERE {field} IS NOT NULL") as c:
                        if c.fetchone()[0] != 0:
                            raise AssertionError("unmasked officer value")
        finally:
            if active:
                rows = self.show("warehouse_before_suspend", f"SHOW WAREHOUSES LIKE '{WAREHOUSE}'")
                if any(r["name"] == WAREHOUSE and r["state"] != "SUSPENDED" for r in rows):
                    self.command("warehouse_suspend", f"ALTER WAREHOUSE {WAREHOUSE} SUSPEND")
                self.evidence["warehouse_after"] = self.show("warehouse_after_suspend", f"SHOW WAREHOUSES LIKE '{WAREHOUSE}'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    output = args.evidence_dir.resolve()
    if output.is_relative_to(seed.ROOT):
        raise ValueError("evidence must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    tables = seed.build()
    (output / "frozen_seed.json").write_text(seed.canonical(tables) + "\n")
    import snowflake.connector

    params = connection_parameters(dict(os.environ), sf.resolve_commit(repo=str(seed.ROOT)))
    with snowflake.connector.connect(**params) as connection:
        runner = Runner(connection)
        runner.evidence["query_tag"] = json.loads(params["session_parameters"]["QUERY_TAG"])
        try:
            if args.preflight_only:
                runner.guard()
            else:
                runner.verify(tables)
        finally:
            (output / "query_evidence.json").write_text(json.dumps(runner.evidence, indent=2, default=str) + "\n")
    print(f"PASS: {'preflight' if args.preflight_only else 'repeat seed load'}; evidence: {output}")


if __name__ == "__main__":
    main()
