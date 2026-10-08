"""Real connectors with mocked SDK clients, plus live smoke tests that only run with credentials."""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest
from target_fixtures import MIXED, mixed_rows, plan, write_parquet

from app.connectors.registry import get_target_meta
from app.connectors.targets.real_bigquery import RealBigQuery
from app.connectors.targets.real_redshift import RealRedshift
from app.connectors.targets.real_synapse import RealSynapse, connection_string
from app.contracts.models import ProfileSpec


def staged(tmp_path, tid, n=20):
    tp = plan(tid, MIXED, {"partition_column": "d"} if tid == "bigquery" else None)
    f = tmp_path / f"{tid}.parquet"
    write_parquet(f, tid, tp, mixed_rows(n))
    return tp, f


def executed(cursor) -> list[str]:
    return [c.args[0] for c in cursor.execute.call_args_list]


@pytest.mark.parametrize(
    "cls,target", [(RealSynapse, "synapse"), (RealRedshift, "redshift"), (RealBigQuery, "bigquery")]
)
def test_missing_credentials_are_actionable(cls, target):
    res = cls(get_target_meta(target), {}, {}).test_connection()
    assert not res.ok and "missing connection settings" in res.message and "(env " in res.message


def test_bigquery_load_uses_parquet_write_truncate_and_no_dml(tmp_path):
    tp, f = staged(tmp_path, "bigquery")
    conn = RealBigQuery(get_target_meta("bigquery"), {"project": "proj"}, {})
    client = conn._client = MagicMock()
    client.get_table.return_value = MagicMock(labels={}, num_rows=20, schema=[])
    res = conn.load(tp, [f], "L1")
    assert res.rows_loaded == 20 and res.method == "load_job_parquet"
    cfg = client.load_table_from_file.call_args.kwargs["job_config"]
    assert cfg.source_format == "PARQUET" and cfg.write_disposition == "WRITE_TRUNCATE"
    src, dst = client.copy_table.call_args.args[:2]
    assert src == "proj.retail_dw.mixed__stg_L1" and dst == "proj.retail_dw.mixed"
    sqls = [c.args[0] for c in client.query.call_args_list]
    assert sqls and all(s.startswith("CREATE TABLE") for s in sqls)
    assert any("PARTITION BY DATE_TRUNC(`d`, MONTH)" in s for s in sqls)
    client.delete_table.assert_any_call("proj.retail_dw.mixed__stg_L1", not_found_ok=True)


def fake_query(sql: str):
    if "checksum" in sql:
        return [(20, "12345")]
    if "GROUP BY" in sql:
        return [(0,)]
    return [(20, 1, 10, 0, 9)]


def test_real_profile_uses_dialect_checksum():
    tp = plan("bigquery", MIXED)
    conn = RealBigQuery(get_target_meta("bigquery"), {"project": "proj"}, {})
    seen = []
    conn._query = lambda sql: seen.append(sql) or fake_query(sql)
    prof = conn.profile(
        tp, ProfileSpec(numeric_columns=["amount"], checksum_columns=["id"], unique_keys=[["id"]])
    )
    assert prof.row_count == 20 and prof.checksum == "12345" and prof.columns[0].sum == "10"
    assert "TO_HEX(MD5(" in seen[-1] and "`proj.retail_dw.mixed`" in seen[-1]


def test_redshift_copy_from_s3_and_swap(tmp_path, monkeypatch):
    import boto3

    s3 = MagicMock()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: s3)
    tp, f = staged(tmp_path, "redshift")
    connection = {
        "host": "h",
        "database": "d",
        "user": "u",
        "password": "p",
        "s3_bucket": "bkt",
        "iam_role_arn": "arn:aws:iam::1:role/copy",
    }
    conn = RealRedshift(get_target_meta("redshift"), connection, {})
    conn._conn = MagicMock()
    cur = conn._conn.cursor.return_value
    cur.fetchall.return_value = [(20,)]
    res = conn.load(tp, [f], "L1")
    sqls = executed(cur)
    assert res.method == "COPY_S3_PARQUET" and res.rows_loaded == 20
    assert s3.upload_file.call_args.args[1:] == ("bkt", "td-migration/retail_dw/mixed/L1/part-00000.parquet")
    copy = next(s for s in sqls if s.startswith("COPY"))
    assert copy == (
        'COPY "retail_dw"."mixed__stg_L1" FROM \'s3://bkt/td-migration/retail_dw/mixed/L1/\' '
        "IAM_ROLE 'arn:aws:iam::1:role/copy' FORMAT AS PARQUET"
    )
    i = sqls.index('DROP TABLE IF EXISTS "retail_dw"."mixed"')
    assert sqls[i + 1] == 'ALTER TABLE "retail_dw"."mixed__stg_L1" RENAME TO "mixed"'
    assert conn._conn.commit.called


def test_redshift_insert_batches_without_s3(tmp_path):
    tp, f = staged(tmp_path, "redshift")
    conn = RealRedshift(
        get_target_meta("redshift"), {"host": "h", "database": "d", "user": "u", "password": "p"}, {}
    )
    conn._conn = MagicMock()
    cur = conn._conn.cursor.return_value
    cur.fetchall.return_value = [(20,)]
    assert conn.load(tp, [f], "L1").method == "INSERT_BATCHES"
    sql, rows = cur.executemany.call_args.args
    assert sql.startswith('INSERT INTO "retail_dw"."mixed__stg_L1"') and len(rows) == 20


def test_synapse_copy_into_and_rename_swap(tmp_path, monkeypatch):
    lake = MagicMock()
    for name in ["azure", "azure.storage"]:
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(
        sys.modules,
        "azure.storage.filedatalake",
        types.SimpleNamespace(DataLakeServiceClient=lambda *a, **k: lake),
    )
    tp, f = staged(tmp_path, "synapse")
    connection = {
        "server": "ws.sql.azuresynapse.net",
        "database": "pool",
        "user": "u",
        "password": "p",
        "adls_account": "acct",
        "adls_container": "stage",
        "adls_sas": "?sv=x",
    }
    conn = RealSynapse(get_target_meta("synapse"), connection, {})
    conn._conn = MagicMock()
    cur = conn._conn.cursor.return_value
    cur.execute.return_value.fetchall.return_value = [(20,)]
    res = conn.load(tp, [f], "L1")
    sqls = executed(cur)
    assert res.method == "COPY_INTO" and res.rows_loaded == 20
    copy = next(s for s in sqls if s.startswith("COPY INTO"))
    assert "FILE_TYPE = 'PARQUET'" in copy and "acct.blob.core.windows.net/stage/td-migration" in copy
    assert any("RENAME OBJECT [retail_dw].[mixed__stg_L1] TO [mixed]" in s for s in sqls)
    assert any("DISTRIBUTION = ROUND_ROBIN" in s and "mixed__stg_L1" in s for s in sqls)
    cs = connection_string(connection)
    assert "ODBC Driver 18" in cs and "Encrypt=yes" in cs and "tcp:ws.sql.azuresynapse.net,1433" in cs


def env_connection(target: str) -> dict:
    return {
        f.key: os.environ[f.env] for f in get_target_meta(target).connection_fields if f.env in os.environ
    }


@pytest.mark.real
@pytest.mark.parametrize(
    "cls,target,env",
    [
        (RealBigQuery, "bigquery", "BIGQUERY_PROJECT"),
        (RealRedshift, "redshift", "REDSHIFT_HOST"),
        (RealSynapse, "synapse", "SYNAPSE_SERVER"),
    ],
)
def test_live_connection(cls, target, env):
    if not os.environ.get(env):
        pytest.skip(f"{env} not set")
    res = cls(get_target_meta(target), env_connection(target), {}).test_connection()
    assert res.ok, res.message
