import csv
import os
import runpy
import sys
from unittest.mock import Mock

import pytest

from bank_model import ROOT
from sf_common import connect, identifier
from sf_landing import contracts, landing_sql
from sf_teardown import teardown_sql


@pytest.mark.parametrize('token', ['', 'lowercase', 'ABC;DROP', 'A-B', "A'B", '../ABC', 'A B'])
def test_invalid_tokens(token):
    with pytest.raises(ValueError):
        landing_sql(token)
    with pytest.raises(ValueError):
        teardown_sql(token)


def test_landing_sql_scope_comments_formats_and_reload():
    sql = landing_sql('FSX_20261105')
    text = ';\n'.join(sql)
    assert 'WAREHOUSE_SIZE=XSMALL AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE' in text
    assert 'TYPE=PARQUET USE_LOGICAL_TYPE=TRUE' in text
    assert 'MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE' in text
    assert 'TYPE=CSV' in text
    assert r"NULL_IF=('\\N')" in text
    assert 'TD_TARGET' in text
    assert not any('TD_TARGET' in s for s in sql if s.startswith(('CREATE TABLE', 'COPY INTO')))
    for statement in sql:
        if statement.startswith('CREATE'):
            assert "COMMENT='run FSX_20261105 expires 2026-11-12T23:59:00Z'" in statement
    reloaded = landing_sql('FSX_20261105', reload=True, selected=['TD_SOURCE.STG_CUSTOMER'])
    assert sum(s.startswith('TRUNCATE') for s in reloaded) == 1
    assert sum(s.startswith('COPY INTO') for s in reloaded) == 1
    assert 'FORCE=TRUE' in ';'.join(reloaded)
    for name, columns in contracts()['TD_BASELINE'].items():
        with (ROOT / 'baseline/teradata' / (name + '.csv')).open(newline='') as stream:
            assert list(columns) == next(csv.reader(stream))
    with pytest.raises(ValueError):
        landing_sql('TOKEN', selected=['TD_SOURCE.STG_CUSTOMER'])
    with pytest.raises(ValueError):
        landing_sql('TOKEN', reload=True, selected=['TD_TARGET.UNKNOWN'])
    with pytest.raises(ValueError):
        landing_sql('TOKEN', expires="2026-01-01' DROP")


def test_teardown_exact_names_and_comment_or_name_listing():
    sql = teardown_sql('FSX_20261105')
    text = ';\n'.join(sql)
    assert text.index(' SUSPEND') < text.index(' SET DATA_RETENTION_TIME_IN_DAYS=0') < text.index('DROP DATABASE')
    assert 'DROP DATABASE IF EXISTS "FSX_20261105_DB"' in text
    assert 'DROP WAREHOUSE IF EXISTS "FSX_20261105_WH"' in text
    assert ' OR CONTAINS(UPPER(COALESCE("comment"' in text
    assert not any(s.startswith('DROP TABLE') for s in sql)
    assert identifier('123') == '"123"'


@pytest.mark.parametrize('script', ['sf_landing.py', 'sf_teardown.py'])
def test_dry_run_never_connects(script, monkeypatch, capsys):
    forbidden = Mock(side_effect=AssertionError('Network forbidden'))
    monkeypatch.setattr('sf_common.connect', forbidden)
    monkeypatch.setattr(sys, 'argv', [script, '--token', 'FSX_20261105', '--dry-run'])
    runpy.run_path(str(ROOT / 'tools' / script), run_name='__main__')
    forbidden.assert_not_called()
    assert 'FSX_20261105_DB' in capsys.readouterr().out


def test_jwt_key_in_memory_and_host_removed(monkeypatch):
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    for k, value in {'ACCOUNT': 'fixture-account', 'USER': 'fixture-user', 'PRIVATE_KEY': pem, 'ROLE': 'FIXTURE_ROLE', 'WAREHOUSE': 'FIXTURE_WH'}.items():
        monkeypatch.setenv('SNOWFLAKE_NFR_' + k, value)
    monkeypatch.setenv('SNOWFLAKE_HOST', 'invalid-host')
    mock = Mock()
    monkeypatch.setattr(snowflake.connector, 'connect', mock)
    connect()
    args = mock.call_args.kwargs
    assert args['authenticator'] == 'SNOWFLAKE_JWT'
    assert isinstance(args['private_key'], bytes)
    assert args['role'] == 'FIXTURE_ROLE' and args['warehouse'] == 'FIXTURE_WH'
    assert 'SNOWFLAKE_HOST' not in os.environ
