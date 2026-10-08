"""Real Amazon Redshift connector: redshift_connector + boto3 (S3 upload + COPY ... FORMAT AS PARQUET),
staging table + transactional swap; INSERT_BATCHES fallback when no S3 bucket/IAM role is configured."""

from __future__ import annotations

import re
import time
from pathlib import Path

from ...contracts.models import ConnectionTestResult, LoadResult, ProfileSpec, TablePlan, TableProfile
from ..registry import register_target
from .ddl_redshift import RedshiftDDL
from .real_common import parquet_rows, timed_test

REQUIRED = ["host", "database", "user", "password"]


@register_target("redshift", "real")
class RealRedshift(RedshiftDDL):
    _conn = None

    @property
    def conn(self):
        if self._conn is None:
            import redshift_connector

            c = self.connection
            self._conn = redshift_connector.connect(
                host=c["host"],
                port=int(c.get("port") or 5439),
                database=c["database"],
                user=c["user"],
                password=c["password"],
                ssl=True,
            )
            self._conn.autocommit = False
        return self._conn

    def _run(self, *statements: str, params: list | None = None) -> None:
        cur = self.conn.cursor()
        try:
            for s in statements:
                cur.execute(s, params) if params else cur.execute(s)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _query(self, sql: str) -> list[tuple]:
        cur = self.conn.cursor()
        cur.execute(sql)
        rows = [tuple(r) for r in cur.fetchall()]
        self.conn.commit()
        return rows

    def test_connection(self) -> ConnectionTestResult:
        return timed_test(self.meta, self.connection, REQUIRED, lambda: self._query("SELECT version()")[0][0])

    def ensure_container(self, container: str) -> None:
        self._run(f"CREATE SCHEMA IF NOT EXISTS {self.q(container)}")

    def _exists(self, table: TablePlan) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
            [table.target_container, table.target_table],
        )
        found = bool(cur.fetchall())
        self.conn.commit()
        return found

    def create_table(self, table: TablePlan) -> None:
        if not self._exists(table):
            self._run(self.render_ddl(table))

    def _use_copy(self, table: TablePlan) -> bool:
        method = table.load_method or self.opt(None, "load_method")
        return method != "INSERT_BATCHES" and bool(
            self.connection.get("s3_bucket") and self.connection.get("iam_role_arn")
        )

    def _upload(self, table: TablePlan, files: list[Path], load_id: str) -> tuple[str, list[str]]:
        import boto3

        s3 = boto3.client("s3", region_name=self.connection.get("aws_region"))
        bucket = self.connection["s3_bucket"]
        prefix = f"td-migration/{table.target_container}/{table.target_table}/{load_id}/"
        keys = []
        for i, f in enumerate(files):
            key = f"{prefix}part-{i:05d}.parquet"
            s3.upload_file(str(f), bucket, key)
            keys.append(key)
        return f"s3://{bucket}/{prefix}", keys

    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        t0 = time.perf_counter()
        stg = f"{table.target_table}__stg_{re.sub(r'[^A-Za-z0-9_]', '_', load_id)}"
        stg_rel = self.qualified(table, stg)
        self._run(f"DROP TABLE IF EXISTS {stg_rel}", self.render_ddl(table, stg))
        details: dict = {"staging_table": stg, "files": len(files)}
        if self._use_copy(table):
            uri, keys = self._upload(table, files, load_id)
            role = self.connection["iam_role_arn"].replace("'", "")
            self._run(f"COPY {stg_rel} FROM '{uri}' IAM_ROLE '{role}' FORMAT AS PARQUET")
            details |= {"method": "COPY_S3_PARQUET", "s3_uri": uri}
            method = "COPY_S3_PARQUET"
        else:
            cols = [c.name for c in self.columns(table)]
            marks = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO {stg_rel} ({', '.join(self.q(c) for c in cols)}) VALUES ({marks})"
            cur = self.conn.cursor()
            for rows in parquet_rows(files):
                cur.executemany(sql, rows)
            self.conn.commit()
            method = "INSERT_BATCHES"
        self._run(
            f"DROP TABLE IF EXISTS {self.qualified(table)}",
            f"ALTER TABLE {stg_rel} RENAME TO {self.q(table.target_table)}",
        )
        rows = int(self._query(f"SELECT COUNT(*) FROM {self.qualified(table)}")[0][0])
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
        self._run(f"DROP TABLE IF EXISTS {self.qualified(table)}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
