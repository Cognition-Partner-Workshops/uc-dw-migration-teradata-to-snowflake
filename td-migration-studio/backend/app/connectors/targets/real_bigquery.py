"""Real Google BigQuery connector (google-cloud-bigquery). Uses only load/copy jobs and queries, so it
works in the free BigQuery sandbox (no DML)."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from ...contracts.models import ConnectionTestResult, LoadResult, ProfileSpec, TablePlan, TableProfile
from ..registry import register_target
from .base import TargetConfigError
from .ddl_bigquery import BigQueryDDL
from .real_common import timed_test


@register_target("bigquery", "real")
class RealBigQuery(BigQueryDDL):
    _client = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import bigquery

            if not self.project:
                raise TargetConfigError("BigQuery: set BIGQUERY_PROJECT (or the 'project' connection field)")
            creds = None
            if self.connection.get("credentials_path"):
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(
                    self.connection["credentials_path"]
                )
            self._client = bigquery.Client(
                project=self.project, credentials=creds, location=self.opt(None, "location") or "US"
            )
        return self._client

    def _query(self, sql: str) -> list[tuple]:
        return [tuple(r.values()) for r in self.client.query(sql).result()]

    def test_connection(self) -> ConnectionTestResult:
        def probe() -> str:
            self._query("SELECT 1")
            return f"BigQuery project {self.project}"

        return timed_test(self.meta, self.connection, ["project"], probe)

    def ensure_container(self, container: str) -> None:
        from google.cloud import bigquery

        ds = bigquery.Dataset(f"{self.project}.{container}")
        ds.location = self.opt(None, "location") or "US"
        self.client.create_dataset(ds, exists_ok=True)

    def _ddl_hash(self, table: TablePlan) -> str:
        return hashlib.sha256(self.render_ddl(table).encode()).hexdigest()[:16]

    def _table_id(self, table: TablePlan, name: str | None = None) -> str:
        return f"{self.project}.{table.target_container}.{name or table.target_table}"

    def create_table(self, table: TablePlan) -> None:
        from google.api_core.exceptions import NotFound

        want = self._ddl_hash(table)
        try:
            existing = self.client.get_table(self._table_id(table))
            if existing.labels.get("td_ddl_hash") == want:
                return
            self.client.delete_table(existing)
        except NotFound:
            pass
        self.client.query(self.render_ddl(table)).result()
        t = self.client.get_table(self._table_id(table))
        t.labels = {**t.labels, "td_ddl_hash": want}
        self.client.update_table(t, ["labels"])

    def load(self, table: TablePlan, files: list[Path], load_id: str) -> LoadResult:
        from google.cloud import bigquery

        t0 = time.perf_counter()
        self.create_table(table)
        stg = f"{table.target_table}__stg_{re.sub(r'[^A-Za-z0-9_]', '_', load_id)}"
        stg_id = self._table_id(table, stg)
        self.client.delete_table(stg_id, not_found_ok=True)
        self.client.query(
            self.render_ddl(table, stg).replace("OPTIONS (require_partition_filter = TRUE)", "")
        ).result()
        schema = self.client.get_table(stg_id).schema
        try:
            for i, f in enumerate(files):
                cfg = bigquery.LoadJobConfig(
                    source_format=bigquery.SourceFormat.PARQUET,
                    write_disposition="WRITE_TRUNCATE" if i == 0 else "WRITE_APPEND",
                    schema=schema,
                    decimal_target_types=["NUMERIC", "BIGNUMERIC", "STRING"],
                )
                with open(f, "rb") as fh:
                    self.client.load_table_from_file(fh, stg_id, job_config=cfg).result()
            copy = bigquery.CopyJobConfig(write_disposition="WRITE_TRUNCATE")
            self.client.copy_table(stg_id, self._table_id(table), job_config=copy).result()
        finally:
            self.client.delete_table(stg_id, not_found_ok=True)
        rows = self.client.get_table(self._table_id(table)).num_rows
        return LoadResult(
            rows_loaded=int(rows or 0),
            load_id=load_id,
            duration_s=time.perf_counter() - t0,
            method="load_job_parquet",
            details={"staging_table": stg, "files": len(files), "swap": "copy job WRITE_TRUNCATE"},
        )

    def profile(self, table: TablePlan, spec: ProfileSpec) -> TableProfile:
        return self.run_profile(table, spec, self.qualified(table), self._query)

    def drop_table(self, table: TablePlan) -> None:
        self.client.delete_table(self._table_id(table), not_found_ok=True)
