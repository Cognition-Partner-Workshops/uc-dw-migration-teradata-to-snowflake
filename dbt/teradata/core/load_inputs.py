"""Load immutable pipe-delimited fixture inputs into an isolated DuckDB schema."""

import json
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = {
    "DIM_CUSTOMER": {
        "CUSTOMER_ID": "INTEGER",
        "CUSTOMER_KEY": "BIGINT",
        "FIRST_NAME": "VARCHAR(50)",
        "LAST_NAME": "VARCHAR(50)",
        "DATE_OF_BIRTH": "DATE",
        "GENDER": "CHAR(1)",
        "MARITAL_STATUS": "CHAR(1)",
        "EMAIL_ADDRESS": "VARCHAR(100)",
        "PHONE_NUMBER": "VARCHAR(20)",
        "ADDRESS_LINE_1": "VARCHAR(100)",
        "ADDRESS_LINE_2": "VARCHAR(100)",
        "CITY": "VARCHAR(50)",
        "STATE_PROVINCE": "VARCHAR(50)",
        "POSTAL_CODE": "VARCHAR(10)",
        "COUNTRY_CODE": "CHAR(3)",
        "CUSTOMER_SEGMENT": "VARCHAR(20)",
        "RISK_SCORE": "DECIMAL(5,2)",
        "CREDIT_RATING": "CHAR(3)",
        "KYC_STATUS": "VARCHAR(15)",
        "ONBOARDING_DATE": "DATE",
        "LAST_REVIEW_DATE": "DATE",
        "IS_ACTIVE": "SMALLINT",
        "EFFECTIVE_FROM": "TIMESTAMP",
        "EFFECTIVE_TO": "TIMESTAMP",
        "CURRENT_FLAG": "CHAR(1)",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP",
        "ETL_UPDATE_TS": "TIMESTAMP"
    },
    "DIM_ACCOUNT": {
        "ACCOUNT_KEY": "BIGINT",
        "ACCOUNT_ID": "VARCHAR(20)",
        "CUSTOMER_ID": "INTEGER",
        "ACCOUNT_TYPE": "VARCHAR(20)",
        "ACCOUNT_SUBTYPE": "VARCHAR(30)",
        "CURRENCY_CODE": "CHAR(3)",
        "OPENING_DATE": "DATE",
        "CLOSING_DATE": "DATE",
        "ACCOUNT_STATUS": "VARCHAR(15)",
        "INTEREST_RATE": "DECIMAL(7,4)",
        "CREDIT_LIMIT": "DECIMAL(15,2)",
        "OVERDRAFT_LIMIT": "DECIMAL(15,2)",
        "BRANCH_ID": "INTEGER",
        "RELATIONSHIP_MGR_ID": "INTEGER",
        "PRODUCT_ID": "INTEGER",
        "IS_JOINT_ACCOUNT": "SMALLINT",
        "TAX_REPORTING_FLAG": "SMALLINT",
        "EFFECTIVE_FROM": "TIMESTAMP",
        "EFFECTIVE_TO": "TIMESTAMP",
        "CURRENT_FLAG": "CHAR(1)",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP",
        "ETL_UPDATE_TS": "TIMESTAMP"
    },
    "DIM_PRODUCT": {
        "PRODUCT_ID": "INTEGER",
        "PRODUCT_CODE": "VARCHAR(20)",
        "PRODUCT_NAME": "VARCHAR(100)",
        "PRODUCT_CATEGORY": "VARCHAR(30)",
        "PRODUCT_SUBCATEGORY": "VARCHAR(50)",
        "BASE_INTEREST_RATE": "DECIMAL(7,4)",
        "MIN_BALANCE": "DECIMAL(15,2)",
        "MAX_BALANCE": "DECIMAL(15,2)",
        "FEE_STRUCTURE": "VARCHAR(20)",
        "MONTHLY_FEE": "DECIMAL(10,2)",
        "IS_REGULATED": "SMALLINT",
        "REGULATORY_CODE": "VARCHAR(20)",
        "LAUNCH_DATE": "DATE",
        "DISCONTINUE_DATE": "DATE",
        "IS_ACTIVE": "SMALLINT",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP"
    },
    "DIM_BRANCH": {
        "BRANCH_ID": "INTEGER",
        "BRANCH_CODE": "CHAR(6)",
        "BRANCH_NAME": "VARCHAR(100)",
        "BRANCH_TYPE": "VARCHAR(20)",
        "ADDRESS_LINE_1": "VARCHAR(100)",
        "CITY": "VARCHAR(50)",
        "COUNTY": "VARCHAR(50)",
        "REGION": "VARCHAR(50)",
        "POSTAL_CODE": "VARCHAR(10)",
        "COUNTRY_CODE": "CHAR(3)",
        "LATITUDE": "DECIMAL(10,7)",
        "LONGITUDE": "DECIMAL(10,7)",
        "MANAGER_ID": "INTEGER",
        "OPENING_DATE": "DATE",
        "CLOSING_DATE": "DATE",
        "IS_ACTIVE": "SMALLINT",
        "EMPLOYEE_COUNT": "SMALLINT",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP"
    },
    "DIM_DATE": {
        "DATE_KEY": "INTEGER",
        "CALENDAR_DATE": "DATE",
        "DAY_OF_WEEK": "SMALLINT",
        "DAY_NAME": "VARCHAR(10)",
        "DAY_OF_MONTH": "SMALLINT",
        "DAY_OF_YEAR": "SMALLINT",
        "WEEK_OF_YEAR": "SMALLINT",
        "ISO_WEEK": "SMALLINT",
        "MONTH_NUM": "SMALLINT",
        "MONTH_NAME": "VARCHAR(15)",
        "MONTH_SHORT": "CHAR(3)",
        "QUARTER_NUM": "SMALLINT",
        "QUARTER_NAME": "CHAR(2)",
        "HALF_YEAR": "SMALLINT",
        "CALENDAR_YEAR": "SMALLINT",
        "FISCAL_YEAR": "SMALLINT",
        "FISCAL_QUARTER": "SMALLINT",
        "IS_WEEKEND": "SMALLINT",
        "IS_NORWEGIAN_HOLIDAY": "SMALLINT",
        "HOLIDAY_NAME": "VARCHAR(50)",
        "IS_BUSINESS_DAY": "SMALLINT",
        "IS_MONTH_END": "SMALLINT",
        "IS_QUARTER_END": "SMALLINT",
        "IS_YEAR_END": "SMALLINT",
        "PRIOR_DAY_DATE": "DATE",
        "NEXT_DAY_DATE": "DATE",
        "SAME_DAY_PREV_YEAR": "DATE"
    },
    "FACT_TRANSACTION": {
        "TRANSACTION_ID": "BIGINT",
        "TRANSACTION_DATE": "DATE",
        "TRANSACTION_TIME": "TIME",
        "TRANSACTION_TS": "TIMESTAMP",
        "ACCOUNT_KEY": "BIGINT",
        "CUSTOMER_KEY": "BIGINT",
        "PRODUCT_ID": "INTEGER",
        "BRANCH_ID": "INTEGER",
        "DATE_KEY": "INTEGER",
        "TRANSACTION_TYPE": "VARCHAR(20)",
        "TRANSACTION_SUBTYPE": "VARCHAR(30)",
        "CHANNEL": "VARCHAR(20)",
        "TRANSACTION_AMOUNT": "DECIMAL(15,2)",
        "TRANSACTION_CURRENCY": "CHAR(3)",
        "BASE_CURRENCY_AMOUNT": "DECIMAL(15,2)",
        "EXCHANGE_RATE": "DECIMAL(12,6)",
        "RUNNING_BALANCE": "DECIMAL(15,2)",
        "MERCHANT_ID": "VARCHAR(20)",
        "MERCHANT_NAME": "VARCHAR(100)",
        "MERCHANT_CATEGORY": "VARCHAR(4)",
        "COUNTERPARTY_ACCT": "VARCHAR(20)",
        "REFERENCE_NUMBER": "VARCHAR(30)",
        "DESCRIPTION_TEXT": "VARCHAR(200)",
        "IS_INTERNATIONAL": "SMALLINT",
        "IS_FLAGGED": "SMALLINT",
        "FLAG_REASON": "VARCHAR(50)",
        "POSTING_DATE": "DATE",
        "VALUE_DATE": "DATE",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP"
    },
    "FACT_MONTHLY_ACCOUNT_SNAPSHOT": {
        "SNAPSHOT_DATE": "DATE",
        "SNAPSHOT_MONTH_KEY": "INTEGER",
        "ACCOUNT_KEY": "BIGINT",
        "CUSTOMER_KEY": "BIGINT",
        "PRODUCT_ID": "INTEGER",
        "BRANCH_ID": "INTEGER",
        "OPENING_BALANCE": "DECIMAL(15,2)",
        "CLOSING_BALANCE": "DECIMAL(15,2)",
        "AVERAGE_BALANCE": "DECIMAL(15,2)",
        "MINIMUM_BALANCE": "DECIMAL(15,2)",
        "MAXIMUM_BALANCE": "DECIMAL(15,2)",
        "TOTAL_DEBITS": "DECIMAL(15,2)",
        "TOTAL_CREDITS": "DECIMAL(15,2)",
        "DEBIT_COUNT": "INTEGER",
        "CREDIT_COUNT": "INTEGER",
        "INTEREST_EARNED": "DECIMAL(12,2)",
        "INTEREST_CHARGED": "DECIMAL(12,2)",
        "FEES_CHARGED": "DECIMAL(12,2)",
        "DAYS_IN_OVERDRAFT": "SMALLINT",
        "DAYS_DORMANT": "SMALLINT",
        "CURRENCY_CODE": "CHAR(3)",
        "BASE_CURRENCY_CLOSING": "DECIMAL(15,2)",
        "ETL_BATCH_ID": "BIGINT",
        "ETL_INSERT_TS": "TIMESTAMP"
    },
    "STG_TRANSACTIONS": {
        "TRANSACTION_ID": "BIGINT",
        "ACCOUNT_ID": "VARCHAR(20)",
        "TRANSACTION_DATE": "DATE",
        "TRANSACTION_TIME": "TIME",
        "TRANSACTION_TYPE": "VARCHAR(20)",
        "TRANSACTION_SUBTYPE": "VARCHAR(30)",
        "CHANNEL": "VARCHAR(20)",
        "TRANSACTION_AMOUNT": "DECIMAL(15,2)",
        "CURRENCY_CODE": "CHAR(3)",
        "MERCHANT_ID": "VARCHAR(20)",
        "MERCHANT_NAME": "VARCHAR(100)",
        "MERCHANT_CATEGORY": "VARCHAR(4)",
        "COUNTERPARTY_ACCT": "VARCHAR(20)",
        "REFERENCE_NUMBER": "VARCHAR(30)",
        "DESCRIPTION_TEXT": "VARCHAR(200)",
        "POSTING_DATE": "DATE",
        "VALUE_DATE": "DATE",
        "LOAD_DATE": "DATE"
    },
    "STG_CUSTOMER": {
        "CUSTOMER_ID": "INTEGER",
        "FIRST_NAME": "VARCHAR(50)",
        "LAST_NAME": "VARCHAR(50)",
        "DATE_OF_BIRTH": "DATE",
        "GENDER": "CHAR(1)",
        "MARITAL_STATUS": "CHAR(1)",
        "EMAIL_ADDRESS": "VARCHAR(100)",
        "PHONE_NUMBER": "VARCHAR(20)",
        "ADDRESS_LINE_1": "VARCHAR(100)",
        "ADDRESS_LINE_2": "VARCHAR(100)",
        "CITY": "VARCHAR(50)",
        "STATE_PROVINCE": "VARCHAR(50)",
        "POSTAL_CODE": "VARCHAR(10)",
        "COUNTRY_CODE": "CHAR(3)",
        "CUSTOMER_SEGMENT": "VARCHAR(20)",
        "RISK_SCORE": "DECIMAL(5,2)",
        "CREDIT_RATING": "CHAR(3)",
        "KYC_STATUS": "VARCHAR(15)"
    },
    "STG_TRANSACTION_ERRORS": {
        "TRANSACTION_ID": "BIGINT",
        "ACCOUNT_ID": "VARCHAR(20)",
        "TRANSACTION_DATE": "DATE",
        "TRANSACTION_TIME": "TIME",
        "TRANSACTION_TYPE": "VARCHAR(20)",
        "TRANSACTION_SUBTYPE": "VARCHAR(30)",
        "CHANNEL": "VARCHAR(20)",
        "TRANSACTION_AMOUNT": "DECIMAL(15,2)",
        "CURRENCY_CODE": "CHAR(3)",
        "MERCHANT_ID": "VARCHAR(20)",
        "MERCHANT_NAME": "VARCHAR(100)",
        "MERCHANT_CATEGORY": "VARCHAR(4)",
        "COUNTERPARTY_ACCT": "VARCHAR(20)",
        "REFERENCE_NUMBER": "VARCHAR(30)",
        "DESCRIPTION_TEXT": "VARCHAR(200)",
        "POSTING_DATE": "DATE",
        "VALUE_DATE": "DATE",
        "LOAD_DATE": "DATE",
        "ERROR_REASON": "VARCHAR(50)",
        "BATCH_ID": "BIGINT"
    },
    "ETL_BATCH_CONTROL": {
        "BATCH_ID": "BIGINT",
        "BATCH_DATE": "DATE",
        "BATCH_STATUS": "VARCHAR(20)",
        "START_TS": "TIMESTAMP",
        "END_TS": "TIMESTAMP"
    },
    "ETL_LOG": {
        "PROCEDURE_NAME": "VARCHAR(128)",
        "BATCH_ID": "BIGINT",
        "LOG_LEVEL": "VARCHAR(10)",
        "LOG_MESSAGE": "VARCHAR(2000)",
        "LOG_TS": "TIMESTAMP"
    },
    "DIM_EXCHANGE_RATES": {
        "FROM_CURRENCY": "CHAR(3)",
        "TO_CURRENCY": "CHAR(3)",
        "RATE_DATE": "DATE",
        "EXCHANGE_RATE": "DECIMAL(12,6)"
    }
}

def load():
    path = Path(os.environ.get("TD_DUCKDB_PATH", "target/td.duckdb"))
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "fixtures/frozen/manifest.json").read_text())
    with duckdb.connect(str(path)) as con:
        con.execute("BEGIN")
        con.execute("CREATE SCHEMA IF NOT EXISTS td_src_core")
        for name, columns in CONTRACT.items():
            entry = manifest["tables"][name]
            if entry["columns"] != list(columns):
                raise ValueError(f"Fixture columns differ: {name}")
            declarations = ", ".join(f'"{col}" {kind}' for col, kind in columns.items())
            con.execute(f'CREATE OR REPLACE TABLE td_src_core."{name}" ({declarations})')
            csv_path = str(ROOT / "fixtures/frozen" / entry["file"]).replace("'", "''")
            con.execute(
                f'COPY td_src_core."{name}" FROM \'{csv_path}\' '
                "(HEADER, DELIMITER '|', NULLSTR '\\N')"
            )
            count = con.execute(f'SELECT count(*) FROM td_src_core."{name}"').fetchone()[0]
            if count != entry["rows"]:
                raise ValueError(f"Fixture row count differs: {name}: {count}")
            print(f"Loaded td_src_core.{name}: {count} rows")
        con.execute("COMMIT")

if __name__ == "__main__":
    load()
