import csv
import json
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

import duckdb

from bank_model import ROOT
from licence_status import markdown, status
from reconcile import compare, normalize, reconcile
from sf_common import column_identifier


def test_normalization_and_tolerance():
    types = {'ID': 'BIGINT', 'AMOUNT': 'DECIMAL(15,2)', 'DAY': 'DATE', 'TS': 'TIMESTAMP', 'TEXT': 'VARCHAR'}
    expected = [dict(ID='1', AMOUNT='1.000000', DAY='2026-01-31', TS='2026-01-31 06:00:00', TEXT=r'\N')]
    actual = [dict(id=1, amount=Decimal('1.0000001'), day='2026-01-31T00:00:00', ts='2026-01-31T07:00:00+01:00', text=None)]
    assert compare(expected, actual, types, ['ID'])['status'] == 'GREEN'
    actual[0]['amount'] = Decimal('1.01')
    assert compare(expected, actual, types, ['ID'])['column_differences'] == {'AMOUNT': 1}
    assert normalize(datetime(9999, 12, 31, 23, 59, 59), 'TIMESTAMP') == datetime(9999, 12, 31, 23, 59, 59)
    assert normalize('2026-01-31garbage', 'DATE') == '2026-01-31garbage'


def test_empty_missing_extra_and_column_errors():
    types = {'ID': 'BIGINT', 'VALUE': 'VARCHAR'}
    assert compare([], [], types, ['ID'])['status'] == 'GREEN'
    assert compare([], [], types, ['ID'], actual_columns=['ID'])['status'] == 'RED'
    result = compare([{'ID': 1, 'VALUE': 'a'}], [{'ID': 2, 'VALUE': 'a'}], types, ['ID'])
    assert result['status'] == 'RED' and len(result['missing_keys']) == len(result['extra_keys']) == 1
    assert compare([], [{'ID': 2, 'VALUE': 'a'}], types, ['ID'])['status'] == 'RED'
    assert compare([{'ID': 1, 'VALUE': None}], [{'ID': 1, 'VALUE': ''}], types, ['ID'])['status'] == 'RED'


def test_multiset_does_not_drop_duplicate_keys():
    rows = [{'ID': 1, 'VALUE': 'a'}, {'ID': 1, 'VALUE': 'b'}, {'ID': 1, 'VALUE': 'a'}]
    types = {'ID': 'BIGINT', 'VALUE': 'VARCHAR'}
    assert compare(rows, list(reversed(rows)), types, ['ID'])['status'] == 'GREEN'
    assert compare(rows, rows[:2], types, ['ID'])['status'] == 'RED'


def test_cli_full_copy_green_altered_copy_red_and_licences(tmp_path):
    baseline = ROOT / 'baseline/teradata'
    database = tmp_path / 'target.duckdb'
    with duckdb.connect(str(database)) as con:
        for path in sorted(baseline.glob('*.csv')):
            with path.open(newline='') as stream:
                header = next(csv.reader(stream))
            cols = ', '.join(column_identifier(c) + ' VARCHAR' for c in header)
            con.execute(f'CREATE TABLE {path.stem} ({cols})')
            con.execute(f"COPY {path.stem} FROM '{path}' (HEADER, NULLSTR '\\N')")
    report_path = tmp_path / 'green.md'
    args = [sys.executable, str(ROOT / 'tools/reconcile.py'), '--duckdb', str(database), '--report', str(report_path)]
    green = subprocess.run(args, capture_output=True, text=True)
    assert green.returncode == 0, green.stderr
    assert green.stdout == 'Full match: True\n'
    report = json.loads(report_path.with_suffix('.json').read_text())
    with (ROOT / 'licence/ledger.csv').open() as stream:
        ledger = list(csv.DictReader(stream))
    assert all(r['status'] == 'RETIRED' for r in status(report, ledger))
    with duckdb.connect(str(database)) as con:
        con.execute("UPDATE DIM_CUSTOMER SET CITY='Altered' WHERE CUSTOMER_KEY='1'")
        con.execute("DELETE FROM DIM_ACCOUNT WHERE ACCOUNT_KEY='1'")
        con.execute('DROP TABLE AML_SCREENING_3')
    red = subprocess.run(args, capture_output=True, text=True)
    assert red.returncode == 1 and red.stdout == 'Full match: False\n'
    report = json.loads(report_path.with_suffix('.json').read_text())
    assert report['tables']['DIM_CUSTOMER']['column_differences'] == {'CITY': 1}
    assert report['tables']['DIM_ACCOUNT']['missing_keys']
    assert report['tables']['AML_SCREENING_3']['error'] == 'CatalogException'
    lines = status(report, ledger)
    assert lines[0]['status'] == 'BLOCKED'
    assert 'DIM_CUSTOMER' in lines[0]['failing_objects']
    assert 'BLOCKED' in markdown(lines)
    licence = subprocess.run([sys.executable, str(ROOT / 'tools/licence_status.py'), '--report', str(report_path.with_suffix('.json')), '--output', str(tmp_path / 'licence.md')], capture_output=True, text=True)
    assert licence.returncode == 0 and 'BLOCKED' in licence.stdout


def test_absent_and_empty_coverage_blocked():
    ledger = [{'line_id': 'A', 'description': 'Synthetic', 'annual_cost': '100', 'covers': 'ABSENT'}]
    assert status({'tables': {}}, ledger)[0]['failing_objects'] == 'ABSENT'
    ledger[0]['covers'] = ''
    assert status({'tables': {}}, ledger)[0]['status'] == 'BLOCKED'


def test_manifest_key_coverage_error(tmp_path):
    (tmp_path / 'manifest.json').write_text('{}')
    with duckdb.connect() as con:
        try:
            reconcile(tmp_path, con, 'main', {'MISSING': ['ID']})
        except ValueError as exc:
            assert 'exactly the same objects' in str(exc)
        else:
            raise AssertionError('Incomplete coverage accepted')
