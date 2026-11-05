import csv
import json
from decimal import Decimal

import duckdb
import pytest

from bank_model import FROZEN, ROOT, tables, verify_manifest
from generate_seed import render
from td_baseline import build, clean, daily, load_seed, scd2


@pytest.fixture(scope='module')
def warehouse():
    with duckdb.connect() as con:
        build(con)
        yield con


def test_frozen_contract_and_bytes():
    manifest = verify_manifest()
    for name, content in render().items():
        assert (FROZEN / name).read_bytes() == content
    with (ROOT / 'data/validation/expected_row_counts.csv').open() as stream:
        for row in csv.DictReader(stream, delimiter='|'):
            assert manifest['tables'][row['TABLE_NAME']]['rows'] == int(row['EXPECTED_ROW_COUNT'])
    assert len(tables()) == 13


def test_scd_null_semantics_and_existing_null_partition(warehouse):
    con = warehouse
    assert con.execute("SELECT count(*) FROM DIM_CUSTOMER").fetchone()[0] == 17
    assert con.execute("SELECT CURRENT_FLAG FROM DIM_CUSTOMER WHERE CUSTOMER_KEY=2").fetchone()[0] == 'N'
    assert con.execute("SELECT CURRENT_FLAG FROM DIM_CUSTOMER WHERE CUSTOMER_KEY=3").fetchone()[0] == 'Y'
    assert con.execute("SELECT CUSTOMER_ID FROM DIM_CUSTOMER WHERE CUSTOMER_ID>2026000").fetchall() == [(2026001,)]
    assert con.execute("SELECT CUSTOMER_KEY FROM DIM_CUSTOMER WHERE CUSTOMER_ID=1002 AND CURRENT_FLAG='Y'").fetchone()[0] == 16


def test_daily_rejects_fx_defaults_and_audit(warehouse):
    con = warehouse
    assert con.execute('SELECT count(*) FROM STG_TRANSACTION_ERRORS').fetchone()[0] == 2
    assert con.execute('SELECT count(*) FROM FACT_TRANSACTION').fetchone()[0] == 50009
    assert con.execute('SELECT BASE_CURRENCY_AMOUNT, EXCHANGE_RATE, RUNNING_BALANCE, IS_FLAGGED FROM FACT_TRANSACTION WHERE TRANSACTION_ID=900006').fetchone() == (Decimal('34500.37'), Decimal('11.500123'), None, 0)
    assert con.execute('SELECT count(*) FROM ETL_LOG').fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM ETL_BATCH_CONTROL WHERE BATCH_STATUS='COMPLETED'").fetchone()[0] == 2


def test_monthly_merge_preserves_omitted_columns_and_first_day_bug(warehouse):
    con = warehouse
    assert con.execute("SELECT count(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT WHERE SNAPSHOT_MONTH_KEY=202601 AND ETL_BATCH_ID=20260131 AND OPENING_BALANCE<>0").fetchone()[0] == 0
    assert con.execute('SELECT count(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT').fetchone()[0] == 1920
    assert con.execute('SELECT count(*) FROM FACT_MONTHLY_ACCOUNT_SNAPSHOT WHERE BASE_CURRENCY_CLOSING IS NULL').fetchone()[0] == 0


def test_macro_results_and_negative_filter_before_qualify(warehouse):
    con = warehouse
    assert con.execute('SELECT count(*) FROM AML_SCREENING_1').fetchone()[0] == 1
    assert con.execute('SELECT count(*) FROM AML_SCREENING_2').fetchone()[0] == 12
    assert con.execute('SELECT count(*) FROM AML_SCREENING_3').fetchone()[0] == 1
    assert con.execute('SELECT CURRENT_BALANCE FROM DAILY_BALANCE_CHECK_2').fetchone()[0] == Decimal('-500')
    assert con.execute('SELECT count(*) FROM CUSTOMER_TXN_HISTORY').fetchone()[0] == 227
    assert con.execute('SELECT count(*) FROM BTEQ_LARGE_TXN_REPORT').fetchone()[0] == 228
    assert con.execute('SELECT count(*) FROM BTEQ_BRANCH_PERFORMANCE').fetchone()[0] == 10


def test_regulatory_qualify_and_all_manifest_counts(warehouse):
    con = warehouse
    assert con.execute('SELECT count(*)=count(DISTINCT TRANSACTION_ID) FROM VW_REGULATORY_LARGE_TRANSACTIONS').fetchone()[0]
    metadata = json.loads((ROOT / 'baseline/teradata/manifest.json').read_text())
    for name, spec in metadata.items():
        query_name = name.replace('BTEQ_AML_SCREENING_', 'AML_SCREENING_')
        assert con.execute(f'SELECT count(*) FROM {query_name}').fetchone()[0] == spec['rows']


def test_sql_comment_stripping_preserves_payee_literal():
    assert clean("SELECT '--' -- comment\n") == "SELECT '--' \n"


def test_empty_staging_is_a_noop_for_data_but_records_success():
    with duckdb.connect() as con:
        load_seed(con)
        con.execute('DELETE FROM STG_CUSTOMER')
        con.execute('DELETE FROM STG_TRANSACTIONS')
        scd2(con)
        daily(con)
        assert con.execute('SELECT count(*) FROM DIM_CUSTOMER').fetchone()[0] == 15
        assert con.execute('SELECT count(*) FROM FACT_TRANSACTION').fetchone()[0] == 50000
        assert con.execute('SELECT count(*) FROM STG_TRANSACTION_ERRORS').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM ETL_LOG').fetchone()[0] == 2
