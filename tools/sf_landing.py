"""Land immutable fixture inputs and derived outputs; never populate TD_TARGET."""

import argparse
import csv
import json
from pathlib import Path

import duckdb

from bank_model import ROOT, tables
from sf_common import column_identifier, comment, connect, identifier
from td_baseline import BASELINE, duck_type, load_seed

DEFAULT_EXPIRES = '2026-11-12T23:59:00Z'


def sf_type(kind):
    if kind.startswith('TIMESTAMP'):
        return 'TIMESTAMP_NTZ'
    if kind.startswith('TIME'):
        return 'TIME'
    if kind in {'BYTEINT', 'SMALLINT', 'INTEGER', 'BIGINT', 'HUGEINT'}:
        return 'NUMBER(38,0)'
    if kind in {'DOUBLE', 'FLOAT'}:
        return 'DOUBLE'
    return kind


def contracts():
    source = {name: {c.name: duck_type(c.declared_type) for c in td.columns} for name, td in tables().items()}
    baseline = {}
    for name, spec in json.loads((BASELINE / 'manifest.json').read_text()).items():
        with (BASELINE / (name + '.csv')).open(newline='') as stream:
            header = next(csv.reader(stream))
        baseline[name] = {c: spec['columns'][c] for c in header}
    return {'TD_SOURCE': source, 'TD_BASELINE': baseline}


def landing_sql(token, expires=DEFAULT_EXPIRES, reload=False, selected=None, directory=None):
    db, wh = identifier(token + '_DB'), identifier(token + '_WH')
    tag = comment(token, expires)
    definitions = contracts()
    selected = set(selected or [])
    known = {f'{schema}.{name}' for schema, objects in definitions.items() for name in objects}
    if selected - known:
        raise ValueError('Unknown qualified table(s): ' + ', '.join(sorted(selected - known)))
    if selected and not reload:
        raise ValueError('--tables requires --reload')
    directory = Path(directory or ROOT / '.warehouse-exit' / token).resolve()
    statements = [
        f'CREATE WAREHOUSE IF NOT EXISTS {wh} WAREHOUSE_SIZE=XSMALL AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE COMMENT={tag}',
        f'CREATE DATABASE IF NOT EXISTS {db} DATA_RETENTION_TIME_IN_DAYS=0 COMMENT={tag}',
    ]
    for schema in ['TD_SOURCE', 'TD_BASELINE', 'TD_TARGET']:
        statements.append(f'CREATE SCHEMA IF NOT EXISTS {db}.{schema} DATA_RETENTION_TIME_IN_DAYS=0 COMMENT={tag}')
    statements.append(f'USE WAREHOUSE {wh}')
    for schema, objects in definitions.items():
        stage = f'{db}.{schema}.FIXTURE_STAGE'
        statements.append(f'CREATE STAGE IF NOT EXISTS {stage} COMMENT={tag}')
        for name, columns in objects.items():
            if selected and f'{schema}.{name}' not in selected:
                continue
            table = f'{db}.{schema}.{identifier(name)}'
            cols = ', '.join(f'{column_identifier(c)} {sf_type(t)}' for c, t in columns.items())
            statements.append(f'CREATE TABLE IF NOT EXISTS {table} ({cols}) DATA_RETENTION_TIME_IN_DAYS=0 COMMENT={tag}')
            if reload:
                statements.append(f'TRUNCATE TABLE {table}')
            if schema == 'TD_SOURCE':
                path = directory / (name + '.parquet')
                statements.extend([
                    f"PUT 'file://{path}' @{stage}/{name}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE",
                    f"COPY INTO {table} FROM @{stage}/{name}/ FILE_FORMAT=(TYPE=PARQUET USE_LOGICAL_TYPE=TRUE) MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE FORCE={'TRUE' if reload else 'FALSE'} ON_ERROR=ABORT_STATEMENT",
                ])
            else:
                path = BASELINE / (name + '.csv')
                statements.extend([
                    f"PUT 'file://{path}' @{stage}/{name}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE",
                    f"""COPY INTO {table} FROM @{stage}/{name}/ FILE_FORMAT=(TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='"' NULL_IF=('\\\\N') EMPTY_FIELD_AS_NULL=FALSE ESCAPE_UNENCLOSED_FIELD=NONE) FORCE={'TRUE' if reload else 'FALSE'} ON_ERROR=ABORT_STATEMENT""",
                ])
    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token', required=True)
    parser.add_argument('--expires', default=DEFAULT_EXPIRES)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--reload', action='store_true')
    parser.add_argument('--tables', nargs='+', help='Qualified TD_SOURCE.TABLE or TD_BASELINE.TABLE names')
    args = parser.parse_args()
    directory = ROOT / '.warehouse-exit' / args.token
    sql = landing_sql(args.token, args.expires, args.reload, args.tables, directory)
    if args.dry_run:
        try:
            print(';\n'.join(sql) + ';')
        except BrokenPipeError:
            pass
        return
    # Authentication and execution happen only after the dry-run branch.
    directory.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        load_seed(con)
        for name in tables():
            path = directory / (name + '.parquet')
            con.execute(f"COPY {name} TO '{path}' (FORMAT PARQUET)")
    with connect() as connection:
        with connection.cursor() as cursor:
            for statement in sql:
                cursor.execute(statement)
    print('Landing complete: ' + args.token + '_DB (TD_TARGET remains empty).')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Landing failed: ' + type(exc).__name__) from None
