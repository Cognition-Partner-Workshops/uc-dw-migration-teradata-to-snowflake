"""Drop only the exact token database and warehouse, then list matching leftovers."""

import argparse
import json

from sf_common import comment, connect, identifier
from sf_landing import DEFAULT_EXPIRES


def teardown_sql(token):
    identifier(token)
    db, wh = identifier(token + '_DB'), identifier(token + '_WH')
    statements = [
        f"SHOW WAREHOUSES LIKE '{token.replace('_', chr(92) + '_')}_WH'",
        f'ALTER WAREHOUSE IF EXISTS {wh} SUSPEND',
        f'ALTER DATABASE IF EXISTS {db} SET DATA_RETENTION_TIME_IN_DAYS=0',
        f'DROP DATABASE IF EXISTS {db}',
        f'DROP WAREHOUSE IF EXISTS {wh}',
    ]
    for show in ['DATABASES', 'WAREHOUSES', 'SCHEMAS IN ACCOUNT', 'TABLES IN ACCOUNT', 'VIEWS IN ACCOUNT', 'STAGES IN ACCOUNT']:
        statements.extend([
            f'SHOW {show}',
            f"""SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE CONTAINS(UPPER("name"), '{token}') OR CONTAINS(UPPER(COALESCE("comment", '')), '{token}')""",
        ])
    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token', required=True)
    parser.add_argument('--expires', default=DEFAULT_EXPIRES)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    comment(args.token, args.expires)
    sql = teardown_sql(args.token)
    if args.dry_run:
        print(';\n'.join(sql) + ';')
        return
    with connect() as connection:
        with connection.cursor() as cursor:
            suspended = False
            for statement in sql:
                if statement.startswith('ALTER WAREHOUSE') and suspended:
                    continue
                cursor.execute(statement)
                if statement.startswith('SHOW WAREHOUSES LIKE'):
                    columns = [d[0].lower() for d in cursor.description]
                    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    exact = [r for r in rows if r['name'] == args.token + '_WH']
                    suspended = not exact or all(r['state'] == 'SUSPENDED' for r in exact)
                if statement.startswith('SELECT'):
                    columns = [d[0] for d in cursor.description]
                    print(json.dumps([dict(zip(columns, row)) for row in cursor.fetchall()], default=str))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Teardown failed: ' + type(exc).__name__) from None
