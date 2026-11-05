"""Synthetic licence retirement is gated on every covered object's full reconciliation."""

import argparse
import csv
import json
from pathlib import Path

from bank_model import ROOT


def status(report, ledger):
    rows = []
    for line in ledger:
        objects = [s.strip() for s in line['covers'].split(';') if s.strip()]
        failing = [name for name in objects if report.get('tables', {}).get(name, {}).get('status') != 'GREEN']
        if not objects:
            failing = ['EMPTY_COVERAGE']
        rows.append({**line, 'status': 'BLOCKED' if failing else 'RETIRED', 'failing_objects': ';'.join(failing)})
    return rows


def markdown(rows):
    lines = ['| Line | Description | Annual cost (synthetic) | Status | Failing objects |', '|---|---|---:|---|---|']
    lines += [f"| {r['line_id']} | {r['description']} | {r['annual_cost']} | {r['status']} | {r['failing_objects']} |" for r in rows]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, default=ROOT / 'licence/ledger.csv')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    with args.ledger.open(newline='') as stream:
        rows = status(json.loads(args.report.read_text()), list(csv.DictReader(stream)))
    table = markdown(rows)
    print(table, end='')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(table)


if __name__ == '__main__':
    main()
