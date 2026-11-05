"""Derived legacy oracle, not a migration implementation or a Teradata execution."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path

import duckdb

from bank_model import FROZEN, ROOT, tables, verify_manifest

BASELINE = ROOT / 'baseline/teradata'
DAY = "DATE '2026-01-31'"
TS = "TIMESTAMP '2026-01-31 06:00:00'"
BATCH = 20260131


def clean(sql: str) -> str:
    sql = re.sub(r"'[^']*(?:''[^']*)*'|/\*.*?\*/|--[^\n]*", lambda m: m[0] if m[0].startswith("'") else '', sql, flags=re.S)
    sql = re.sub(r'\bSEL\b', 'SELECT', sql)
    sql = sql.replace('BANKING_DW.', '')
    sql = re.sub(r'\s*\(FORMAT\s+\'[^\']*\'\)', '', sql)
    sql = sql.replace('(NOT CASESPECIFIC)', '')
    sql = sql.replace('CURRENT_TIMESTAMP(0)', TS).replace('CURRENT_DATE', DAY)
    sql = re.sub(r'ZEROIFNULL\(([^()]*)\)', r'coalesce(\1, 0)', sql)
    sql = re.sub(r'NULLIFZERO\((SUM\(SUM\(.*?\)\).*?\))\)', r'nullif(\1, 0)', sql, flags=re.S)
    sql = re.sub(r'ADD_MONTHS\(([^,]+),\s*(-?\d+)\)', r"(\1 + INTERVAL '\2 MONTH')", sql)
    return sql


def source(path: str) -> str:
    return (ROOT / path).read_text()


def duck_type(declared: str) -> str:
    return re.sub(r'\bBYTEINT\b', 'SMALLINT', declared).replace('TIME(0)', 'TIME').replace('TIMESTAMP(0)', 'TIMESTAMP').replace('TIMESTAMP(6)', 'TIMESTAMP')


def load_seed(con):
    verify_manifest()
    for name, td in tables().items():
        cols = ', '.join(f'{c.name} {duck_type(c.declared_type)}' for c in td.columns)
        con.execute(f'CREATE TABLE {name} ({cols})')
        con.execute(f"COPY {name} FROM '{FROZEN / (name.lower() + '.csv')}' (HEADER, DELIMITER '|', NULLSTR '\\N')")


def scd2(con):
    tracked = ['CUSTOMER_SEGMENT', 'RISK_SCORE', 'CREDIT_RATING', 'KYC_STATUS', 'ADDRESS_LINE_1', 'CITY', 'STATE_PROVINCE', 'POSTAL_CODE', 'MARITAL_STATUS']
    comparisons = [f's.{c} <> t.{c}' for c in tracked]
    comparisons += [f"coalesce(s.{c}, '') <> coalesce(t.{c}, '')" for c in ['PHONE_NUMBER', 'EMAIL_ADDRESS']]
    con.execute(f"UPDATE DIM_CUSTOMER t SET CURRENT_FLAG='N', EFFECTIVE_TO={TS}, ETL_UPDATE_TS={TS}, ETL_BATCH_ID={BATCH} FROM STG_CUSTOMER s WHERE t.CUSTOMER_ID=s.CUSTOMER_ID AND t.CURRENT_FLAG='Y' AND ({' OR '.join(comparisons)})")
    # Existing-null partition is intentional: only one brand-new customer survives QUALIFY.
    con.execute(f"""CREATE TEMP TABLE scd_insert AS SELECT s.*, coalesce(e.ONBOARDING_DATE, {DAY}) AS ONBOARDING_DATE
        FROM STG_CUSTOMER s LEFT JOIN DIM_CUSTOMER e ON s.CUSTOMER_ID=e.CUSTOMER_ID AND e.CURRENT_FLAG='N'
        WHERE s.CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM DIM_CUSTOMER WHERE CURRENT_FLAG='Y')
        QUALIFY row_number() OVER (PARTITION BY e.CUSTOMER_ID ORDER BY e.EFFECTIVE_TO DESC, s.CUSTOMER_ID, e.CUSTOMER_KEY)=1""")
    columns = [c.name for c in tables()['DIM_CUSTOMER'].columns]
    expressions = {c: f's.{c}' for c in columns}
    expressions.update(CUSTOMER_KEY='(SELECT max(CUSTOMER_KEY) FROM DIM_CUSTOMER) + row_number() OVER (ORDER BY s.CUSTOMER_ID)', COUNTRY_CODE="coalesce(s.COUNTRY_CODE, 'NOR')", LAST_REVIEW_DATE=DAY, IS_ACTIVE='1', EFFECTIVE_FROM=TS, EFFECTIVE_TO="TIMESTAMP '9999-12-31 23:59:59'", CURRENT_FLAG="'Y'", ETL_BATCH_ID=str(BATCH), ETL_INSERT_TS=TS, ETL_UPDATE_TS=TS)
    con.execute(f"INSERT INTO DIM_CUSTOMER SELECT {', '.join(expressions[c] for c in columns)} FROM scd_insert s")


def daily(con):
    sql = clean(source('dml/stored_procedures/sp_load_daily_transactions.sql'))
    reject = sql[sql.index('INSERT INTO STG_TRANSACTION_ERRORS'):sql.index('SET v_error_count')]
    reject = reject.replace('p_batch_date', DAY).replace('p_batch_id', str(BATCH))
    con.execute(reject)
    insert = sql[sql.index('INSERT INTO FACT_TRANSACTION'):sql.index('SET p_rows_inserted = ACTIVITY_COUNT')]
    insert = insert.replace('p_batch_date', DAY).replace('p_batch_id', str(BATCH))
    insert = insert.replace("stg.TRANSACTION_DATE (TIMESTAMP(6)) + (stg.TRANSACTION_TIME - TIME '00:00:00' HOUR TO SECOND)", 'stg.TRANSACTION_DATE + stg.TRANSACTION_TIME')
    insert = insert.replace("CAST(CAST(stg.TRANSACTION_DATE AS DATE FORMAT 'YYYYMMDD') AS INTEGER)", "CAST(strftime(stg.TRANSACTION_DATE, '%Y%m%d') AS INTEGER)")
    con.execute(insert)
    con.execute(f'UPDATE FACT_TRANSACTION SET IS_FLAGGED=0 WHERE ETL_BATCH_ID={BATCH} AND TRANSACTION_ID >= 900000')
    inserted = con.execute(f'SELECT count(*) FROM FACT_TRANSACTION WHERE ETL_BATCH_ID={BATCH} AND TRANSACTION_ID >= 900000').fetchone()[0]
    rejected = con.execute(f'SELECT count(*) FROM STG_TRANSACTION_ERRORS WHERE BATCH_ID={BATCH}').fetchone()[0]
    for message in ['Started loading transactions for date: 2026-01-31', f'Completed. Inserted: {inserted}, Rejected: {rejected}, Duration: 0']:
        con.execute(f"INSERT INTO ETL_LOG VALUES ('SP_LOAD_DAILY_TRANSACTIONS', {BATCH}, 'INFO', ?, {TS})", [message])
    con.execute(f"INSERT INTO ETL_BATCH_CONTROL VALUES ({BATCH}, {DAY}, 'COMPLETED', {TS}, {TS})")


def monthly(con):
    sql = clean(source('dml/stored_procedures/sp_monthly_snapshot.sql'))
    aggregate = sql[sql.index('SELECT\n'):sql.index(') WITH DATA')]
    aggregate = aggregate.replace('v_period_start', "DATE '2026-01-01'").replace('v_period_end', DAY)
    con.execute('CREATE TEMP TABLE VT_TXN_AGGREGATES AS ' + aggregate)
    merge = sql[sql.index('MERGE INTO'):sql.index('SET p_rows_merged = ACTIVITY_COUNT')]
    for old, new in {'v_snapshot_date': DAY, 'v_snapshot_month_key': '202601', 'v_prev_snapshot_date': "DATE '2025-12-01'", 'v_period_end': DAY, 'v_period_start': "DATE '2026-01-01'", 'p_batch_id': str(BATCH)}.items():
        merge = re.sub(r'\b' + old + r'\b', new, merge)
    merge = merge.replace('a.CUSTOMER_KEY', 'c.CUSTOMER_KEY')
    merge = re.sub(r'\s*\(SMALLINT\)', '', merge)
    con.execute(merge)


def view_sql(path: str) -> str:
    sql = clean(source(path))
    sql = sql[sql.index('SELECT\n'):sql.index(';')]
    if 'ROW_HASH' in sql:
        sql = sql.replace('HASHROW(ft.TRANSACTION_ID, ft.TRANSACTION_DATE)', "md5(cast(ft.TRANSACTION_ID AS VARCHAR) || '|' || cast(ft.TRANSACTION_DATE AS VARCHAR))")
        sql = sql.replace('ORDER BY ft.ETL_BATCH_ID DESC)', 'ORDER BY ft.ETL_BATCH_ID DESC, ft.TRANSACTION_DATE DESC, ft.ACCOUNT_KEY)')
    if 'CSUM' in sql:
        sql = sql.replace("TRIM(d.CALENDAR_YEAR)", 'cast(d.CALENDAR_YEAR AS VARCHAR)')
        sql = sql.replace('CSUM(SUM(snap.FEES_CHARGED), snap.SNAPSHOT_MONTH_KEY)', 'SUM(SUM(snap.FEES_CHARGED)) OVER (ORDER BY snap.SNAPSHOT_MONTH_KEY, b.BRANCH_ID ROWS UNBOUNDED PRECEDING)')
        sql = sql.replace('MAVG(SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS), 3, snap.SNAPSHOT_MONTH_KEY)', 'AVG(SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS)) OVER (ORDER BY snap.SNAPSHOT_MONTH_KEY, b.BRANCH_ID ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)')
    return sql


def macro_queries(path: str) -> list[str]:
    sql = clean(source(path))
    sql = sql[sql.index('AS (') + 4:sql.rindex(');')]
    parameters = {'screening_date': DAY, 'lookback_days': '30', 'amount_threshold': '50000.00', 'check_date': DAY, 'cust_id': '1010', 'start_date': f'({DAY} - 30)', 'end_date': DAY, 'txn_type': "'ALL'"}
    for key, value in parameters.items():
        sql = sql.replace(':' + key, value)
    sql = sql.replace('SAMPLE 1000', 'LIMIT 1000')
    queries = [q.strip() for q in sql.split(';') if q.strip()]
    if 'daily_balance' in path:
        summary = queries[0]
        start = summary.index('    QUALIFY')
        end = summary.index('    GROUP BY')
        qualify = summary[start:end].replace('ORDER BY ft.TRANSACTION_TS DESC)', 'ORDER BY ft.TRANSACTION_TS DESC, ft.TRANSACTION_ID DESC, ft.ETL_BATCH_ID DESC)')
        from_start = summary.index('    FROM')
        inner = 'SELECT a.ACCOUNT_TYPE, a.CURRENCY_CODE, ft.RUNNING_BALANCE, ft.ACCOUNT_KEY, ft.TRANSACTION_TS, ft.TRANSACTION_ID, ft.ETL_BATCH_ID\n' + summary[from_start:start] + qualify
        queries[0] = summary[:from_start].replace('a.', '').replace('ft.', '') + ' FROM (' + inner + ') latest\n' + summary[end:].replace('a.', '')
        queries[1] = queries[1].replace('ORDER BY ft.TRANSACTION_TS DESC)', 'ORDER BY ft.TRANSACTION_TS DESC, ft.TRANSACTION_ID DESC, ft.ETL_BATCH_ID DESC)')
    return queries


def build(con):
    load_seed(con)
    scd2(con)
    daily(con)
    monthly(con)
    outputs = {name: f'SELECT * FROM {name}' for name in tables()}
    for path in sorted((ROOT / 'ddl/views').glob('*.sql')):
        name = path.stem[3:].upper()
        con.execute(f'CREATE VIEW {name} AS ' + view_sql(str(path.relative_to(ROOT))))
        outputs[name] = f'SELECT * FROM {name}'
    for macro, count in [('daily_balance_check', 2), ('aml_screening', 3), ('customer_txn_history', 1)]:
        for i, query in enumerate(macro_queries(f'dml/macros/macro_{macro}.sql'), 1):
            name = macro.upper() + (f'_{i}' if count > 1 else '')
            con.execute(f'CREATE TABLE {name} AS {query}')
            outputs[name] = f'SELECT * FROM {name}'
    bteq = clean(source('dml/scripts/bteq_extract_report.btq'))
    extracts = re.findall(r'SELECT\s*\n(.*?);', bteq, re.S)[:2]
    for name, query in zip(['BTEQ_LARGE_TXN_REPORT', 'BTEQ_BRANCH_PERFORMANCE'], extracts):
        query = 'SELECT\n' + query
        query = re.sub(r'\s*\((?:BIGINT,\s*FORMAT\s*\'[^\']*\'|CHAR\(\d+\))\)', '', query)
        con.execute(f'CREATE TABLE {name} AS {query}')
        outputs[name] = f'SELECT * FROM {name}'
    for i in range(1, 4):
        outputs[f'BTEQ_AML_SCREENING_{i}'] = f'SELECT * FROM AML_SCREENING_{i}'
    return outputs


def render() -> dict[str, bytes]:
    with duckdb.connect() as con:
        outputs = build(con)
        files = {}
        metadata = {}
        for name, query in outputs.items():
            result = con.execute(query)
            columns = [d[0].upper() for d in result.description]
            types = [str(d[1]) for d in result.description]
            rows = result.fetchall()
            stream = io.StringIO(newline='')
            writer = csv.writer(stream, lineterminator='\n')
            writer.writerow(columns)
            normalized = [[r'\N' if v is None else str(v) for v in row] for row in rows]
            writer.writerows(sorted(normalized))
            files[name + '.csv'] = stream.getvalue().encode()
            metadata[name] = {'columns': dict(zip(columns, types)), 'rows': len(rows)}
        files['manifest.json'] = (json.dumps(metadata, indent=2, sort_keys=True) + '\n').encode()
        return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=BASELINE)
    args = parser.parse_args()
    files = render()
    if args.check:
        if {p.name for p in args.output.glob('*.csv')} != {n for n in files if n.endswith('.csv')}:
            raise SystemExit('Baseline object set differs')
        for name, content in files.items():
            if not (args.output / name).exists() or (args.output / name).read_bytes() != content:
                raise SystemExit(f'Baseline differs: {name}')
        print(f'Baseline regenerates byte-for-byte ({len(files)-1} objects; derived, not executed).')
    else:
        if any(args.output.glob('*.csv')):
            raise SystemExit('Refusing to overwrite baseline; use --check or a new --output directory.')
        args.output.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (args.output / name).write_bytes(content)
        print(f'Created derived baseline ({len(files)-1} objects).')


if __name__ == '__main__':
    main()
