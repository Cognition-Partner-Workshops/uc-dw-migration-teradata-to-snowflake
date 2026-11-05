"""Full keyed row reconciliation against a frozen derived baseline."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb

from bank_model import ROOT
from sf_common import connect, identifier


def normalize(value, kind):
    if value is None:
        return None
    text = str(value)
    if any(t in kind.upper() for t in ['INT', 'DECIMAL', 'NUMBER', 'DOUBLE', 'FLOAT']):
        try:
            return Decimal(text)
        except InvalidOperation:
            return text
    if 'TIMESTAMP' in kind:
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            return text
    if kind == 'DATE':
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text).date()
            except ValueError:
                return text
    if kind == 'TIME':
        try:
            return time.fromisoformat(text)
        except ValueError:
            return text
    return text


def equal(a, b, tolerance):
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a.is_finite() and b.is_finite() and abs(a - b) <= tolerance
    return a == b


def read_baseline(path):
    with path.open(newline='') as stream:
        return [{column: None if value == r'\N' else value for column, value in row.items()}
                for row in csv.DictReader(stream)]


def compare(expected, actual, types, keys, tolerance=Decimal('0.000001'), actual_columns=None):
    columns = list(types)
    actual_columns = [c.upper() for c in (actual_columns if actual_columns is not None else (actual[0] if actual else columns))]
    missing_columns = sorted(set(columns) - set(actual_columns))
    extra_columns = sorted(set(actual_columns) - set(columns))

    def indexed(rows):
        index = defaultdict(list)
        for row in rows:
            row = {k.upper(): v for k, v in row.items()}
            normalized = {c: normalize(row.get(c), types[c]) for c in columns}
            index[tuple(normalized[k] for k in keys)].append(normalized)
        return index

    left, right = indexed(expected), indexed(actual)
    missing, extra = [], []
    diffs = defaultdict(int)
    matched = 0
    duplicate_keys = []
    for key in sorted(left.keys() | right.keys(), key=str):
        a, b = left.get(key, []), right.get(key, [])
        if len(a) > 1 or len(b) > 1:
            duplicate_keys.append(str(key))
        # Multiset matching preserves repeated result rows rather than dropping them.
        remaining = list(b)
        unmatched = []
        for row in a:
            found = next((i for i, other in enumerate(remaining) if all(equal(row[c], other[c], tolerance) for c in columns)), None)
            if found is not None:
                remaining.pop(found)
                matched += 1
            else:
                unmatched.append(row)
        paired = min(len(unmatched), len(remaining))
        for row, other in zip(unmatched[:paired], remaining[:paired]):
            for c in columns:
                if not equal(row[c], other[c], tolerance):
                    diffs[c] += 1
        missing.extend([str(key)] * (len(unmatched) - paired))
        extra.extend([str(key)] * (len(remaining) - paired))
    green = len(expected) == len(actual) == matched and not missing_columns and not extra_columns
    return dict(status='GREEN' if green else 'RED', baseline_rows=len(expected), actual_rows=len(actual), matched_rows=matched, column_differences=dict(diffs), missing_columns=missing_columns, extra_columns=extra_columns, missing_keys=missing, extra_keys=extra, repeated_keys=duplicate_keys)


def reconcile(baseline, connection, schema, keys, snowflake=False, tolerance=Decimal('0.000001')):
    metadata = json.loads((baseline / 'manifest.json').read_text())
    files = {p.stem for p in baseline.glob('*.csv')}
    if files != set(metadata) or files != set(keys):
        raise ValueError('Baseline, manifest and key specification must cover exactly the same objects')
    prefix = '.'.join(identifier(p.upper()) for p in schema.split('.'))
    report = {'full_match': True, 'tables': {}}
    for name, spec in sorted(metadata.items()):
        try:
            query = f'SELECT * FROM {prefix}.{identifier(name)}'
            cursor = connection.cursor() if snowflake else connection
            cursor.execute(query)
            columns = [d[0].upper() for d in cursor.description]
            actual = [dict(zip(columns, row)) for row in cursor.fetchall()]
            result = compare(read_baseline(baseline / (name + '.csv')), actual, spec['columns'], keys[name], tolerance, columns)
            if snowflake:
                cursor.close()
        except Exception as exc:
            # Connector messages can contain sensitive connection details.
            result = {'status': 'RED', 'error': type(exc).__name__, 'baseline_rows': spec['rows']}
        report['tables'][name] = result
        report['full_match'] &= result['status'] == 'GREEN'
    return report


def markdown(report):
    lines = ['# Reconciliation', '', '| Object | Status | Baseline rows | Actual rows | Matched rows |', '|---|---|---:|---:|---:|']
    for name, result in report['tables'].items():
        lines.append(f"| {name} | {result['status']} | {result.get('baseline_rows', '')} | {result.get('actual_rows', '')} | {result.get('matched_rows', '')} |")
        if result['status'] != 'GREEN':
            lines.extend(['', f'`{name}`: ' + json.dumps(result, sort_keys=True), ''])
    lines.extend(['', 'Full match: ' + str(report['full_match'])])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'baseline/teradata')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--duckdb', type=Path)
    target.add_argument('--snowflake', metavar='DATABASE.SCHEMA')
    parser.add_argument('--schema', default='main')
    parser.add_argument('--keys', type=Path, default=ROOT / 'tools/keys/teradata_keys.json')
    parser.add_argument('--tolerance', type=Decimal, default=Decimal('0.000001'))
    parser.add_argument('--report', type=Path, required=True, help='Markdown path; JSON written alongside')
    args = parser.parse_args()
    if not args.tolerance.is_finite() or args.tolerance < 0:
        parser.error('Tolerance must be finite and non-negative')
    if args.snowflake and len(args.snowflake.split('.')) != 2:
        parser.error('--snowflake requires DATABASE.SCHEMA')
    schema = args.snowflake or args.schema
    for part in schema.split('.'):
        identifier(part.upper())
    connection = connect() if args.snowflake else duckdb.connect(str(args.duckdb), read_only=True)
    try:
        report = reconcile(args.baseline, connection, schema, json.loads(args.keys.read_text()), bool(args.snowflake), args.tolerance)
    finally:
        connection.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown(report))
    args.report.with_suffix('.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('Full match: ' + str(report['full_match']))
    raise SystemExit(0 if report['full_match'] else 1)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Reconciliation failed: ' + type(exc).__name__) from None
