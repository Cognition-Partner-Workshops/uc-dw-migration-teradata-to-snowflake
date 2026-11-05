"""Offline characterization of the reporting SQL against the derived contract."""

import csv
import json
import re
from pathlib import Path

import duckdb
import pytest

from reconcile import compare, read_baseline

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'dbt/teradata/reporting'
BASELINE = ROOT / 'baseline/teradata'
CORE = ['DIM_ACCOUNT', 'DIM_BRANCH', 'DIM_CUSTOMER', 'DIM_DATE',
        'FACT_MONTHLY_ACCOUNT_SNAPSHOT', 'FACT_TRANSACTION']
ORDER = ['VW_CUSTOMER_360', 'VW_REGULATORY_LARGE_TRANSACTIONS', 'VW_BRANCH_PERFORMANCE',
         'AML_SCREENING_1', 'AML_SCREENING_2', 'AML_SCREENING_3', 'CUSTOMER_TXN_HISTORY',
         'DAILY_BALANCE_CHECK_1', 'DAILY_BALANCE_CHECK_2', 'BTEQ_AML_SCREENING_1',
         'BTEQ_AML_SCREENING_2', 'BTEQ_AML_SCREENING_3', 'BTEQ_BRANCH_PERFORMANCE',
         'BTEQ_LARGE_TXN_REPORT']


@pytest.mark.parametrize('empty', [False, True])
def test_reporting_contract(empty):
    manifest = json.loads((BASELINE / 'manifest.json').read_text())
    keys = json.loads((ROOT / 'tools/keys/teradata_keys.json').read_text())
    with duckdb.connect() as con:
        for name in CORE:
            with (BASELINE / f'{name}.csv').open() as stream:
                columns = next(csv.reader(stream))
            declarations = ', '.join(f'"{c}" {manifest[name]["columns"][c]}' for c in columns)
            con.execute(f'CREATE TABLE {name} ({declarations})')
            if not empty:
                con.execute(f"COPY {name} FROM '{BASELINE / (name + '.csv')}' (HEADER, NULLSTR '\\N')")
        for name in ORDER:
            sql = (PROJECT / 'models' / f'{name}.sql').read_text()
            sql = re.sub(r"\{\{ source\('core', '(\w+)'\) \}\}", r'\1', sql)
            sql = re.sub(r"\{\{ ref\('(\w+)'\) \}\}", r'\1', sql)
            sql = sql.replace("to_char(ft.TRANSACTION_DATE, 'YYYY-MM-DD')",
                              'cast(ft.TRANSACTION_DATE AS VARCHAR)')
            con.execute(f'CREATE TABLE {name} AS {sql}')
            result = con.execute(f'SELECT * FROM {name}')
            columns = [d[0].upper() for d in result.description]
            actual = [dict(zip(columns, row)) for row in result.fetchall()]
            expected = [] if empty else read_baseline(BASELINE / f'{name}.csv')
            comparison = compare(expected, actual, manifest[name]['columns'], keys[name],
                                 actual_columns=columns)
            assert comparison['status'] == 'GREEN', (name, comparison)
            with (BASELINE / f'{name}.csv').open() as stream:
                assert columns == [c.upper() for c in next(csv.reader(stream))]
