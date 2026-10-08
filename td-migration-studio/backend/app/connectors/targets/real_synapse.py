"""Real Azure Synapse dedicated SQL pool connector: pyodbc (ODBC Driver 18, Encrypt=yes), Parquet upload to
ADLS Gen2 + COPY INTO a staging table created from the native DDL, then RENAME OBJECT swap.
Falls back to batched INSERTs over ODBC when no ADLS account is configured."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ...contracts.models import ConnectionTestResult, LoadResult, ProfileSpec, TablePlan, TableProfile
from ..registry import register_target
from .ddl_synapse import SynapseDDL
from .real_common import parquet_rows, timed_test

REQUIRED = ["server", "database", "user", "password"]


def connection_string(c: dict) -> str:
    server = c["server"] if c["server"].startswith("tcp:") else f"tcp:{c['server']},1433"
    return (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={server};Database={c['database']};Uid={c['user']};Pwd={{{c['password']}}};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


@register_target("synapse", "real")
class RealSynapse(SynapseDDL):
    _conn = None

    @property
    def conn(self):
        if self._conn is None:
            import pyodbc

            self._conn = pyodbc.connect(connection_string(self.connection), autocommit=True)
        return self._conn

    def _run(self, *statements: str) -> None:
        cur = self.conn.cursor()
        for s in statements:
            cur.execute(s)

    def _query(self, sql: str) -> list[tuple]:
        return [tuple(r) for r in self.conn.cursor().execute(sql).fetchall()]

    def test_connection(self) -> ConnectionTestResult:
        return timed_test(self.meta, self.connection, REQUIRED, lambda: self._query("SELECT @@VERSION")[0][0])

    def ensure_container(self, container: str) -> None:
        name = container.replace("'", "''")
        self._run(f"IF SCHEMA_ID('{name}') IS NULL EXEC('CREATE SCHEMA {self.q(container)}')")

    def _object_id(self, table: TablePlan, name: str | None = None) -> str:
        return self.qualified(table, name).replace("'", "''")

    def create_table(self, table: TablePlan) -> None:
        self._run(f"IF OBJECT_ID('{self._object_id(table)}') IS NULL\n{self.render_ddl(table)}")

    def _sas(self) -> str | None:
        return self.connection.get("adls_sas") or os.environ.get("SYNAPSE_ADLS_SAS")

    def _upload(self, table: TablePlan, files: list[Path], load_id: str) -> str:
        from azure.storage.filedatalake import DataLakeServiceClient

        account, container = self.connection["adls_account"], self.connection["adls_container"]
        cred = self._sas()
        if cred is None:
            from azure.identity import DefaultAzureCredential

            cred = DefaultAzureCredential()
        fs = DataLakeServiceClient(
            f"https://{account}.dfs.core.windows.net", credential=cred
        ).get_file_system_client(container)
        prefix = f"td-migration/{table.target_container}/{table.target_table}/{load_id}"
        for i, f in enumerate(files):
            with open(f, "rb") as fh:
                fs.get_file_client(f"{prefix}/part-{i:05d}.parquet").upload_data(fh, overwrite=True)
        return f"https://{account}.blob.core.windows.net/{container}/{prefix}/*.parquet"

    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        t0 = time.perf_counter()
        safe = re.sub(r"[^A-Za-z0-9_]", "_", load_id)
        stg, old = f"{table.target_table}__stg_{safe}", f"{table.target_table}__old_{safe}"
        stg_rel = self.qualified(table, stg)
        self._run(f"IF OBJECT_ID('{self._object_id(table, stg)}') IS NOT NULL DROP TABLE {stg_rel}")
        self._run(self.render_ddl(table, stg))
        details: dict = {"staging_table": stg, "files": len(files)}
        if self.connection.get("adls_account") and self.connection.get("adls_container") and files:
            uri = self._upload(table, files, load_id)
            sas = self._sas()
            cred = (
                f"CREDENTIAL = (IDENTITY = 'Shared Access Signature', SECRET = '{sas.lstrip('?')}')"
                if sas
                else "CREDENTIAL = (IDENTITY = 'Managed Identity')"
            )
            self._run(f"COPY INTO {stg_rel} FROM '{uri}' WITH (FILE_TYPE = 'PARQUET', {cred})")
            method, details["uri"] = "COPY_INTO", uri
        else:
            cols = [c.name for c in self.columns(table)]
            names, marks = ", ".join(self.q(c) for c in cols), ", ".join("?" * len(cols))
            sql = f"INSERT INTO {stg_rel} ({names}) VALUES ({marks})"
            cur = self.conn.cursor()
            cur.fast_executemany = True
            for rows in parquet_rows(files):
                cur.executemany(sql, rows)
            method = "INSERT_BATCHES"
        final = self._object_id(table)
        self._run(
            f"IF OBJECT_ID('{final}') IS NOT NULL RENAME OBJECT {self.qualified(table)} TO {self.q(old)}",
            f"RENAME OBJECT {stg_rel} TO {self.q(table.target_table)}",
            f"IF OBJECT_ID('{self._object_id(table, old)}') IS NOT NULL "
            f"DROP TABLE {self.qualified(table, old)}",
        )
        rows = int(self._query(f"SELECT COUNT_BIG(*) FROM {self.qualified(table)}")[0][0])
        details["swap"] = "RENAME OBJECT"
        return LoadResult(
            rows_loaded=rows,
            load_id=load_id,
            duration_s=time.perf_counter() - t0,
            method=method,
            details=details,
        )

    def profile(self, table: TablePlan, spec: ProfileSpec) -> TableProfile:
        return self.run_profile(table, spec, self.qualified(table), self._query)

    def drop_table(self, table: TablePlan) -> None:
        self._run(f"IF OBJECT_ID('{self._object_id(table)}') IS NOT NULL DROP TABLE {self.qualified(table)}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
