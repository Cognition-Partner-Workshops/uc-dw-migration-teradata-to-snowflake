# Inferred DDL contract

No source DDL exists for these six objects. Every column below is inferred from the unchanged legacy consumer, not from a live Teradata catalog. Required identifiers and load dates are explicit fixture contracts; nullable attributes preserve missing values. No uniqueness constraint is invented for staging or ETL_LOG. Types and capacities are assumptions for owner review, not signed business exceptions.

## STG_TRANSACTIONS

Consumer: `dml/stored_procedures/sp_load_daily_transactions.sql`: staging projection, filter and account join; types from FACT_TRANSACTION/DIM_ACCOUNT.

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| TRANSACTION_ID | BIGINT | NOT NULL |
| ACCOUNT_ID | VARCHAR(20) | NOT NULL |
| TRANSACTION_DATE | DATE | NOT NULL |
| TRANSACTION_TIME | TIME(0) | nullable |
| TRANSACTION_TYPE | VARCHAR(20) | NOT CASESPECIFIC NOT NULL |
| TRANSACTION_SUBTYPE | VARCHAR(30) | NOT CASESPECIFIC |
| CHANNEL | VARCHAR(20) | NOT CASESPECIFIC |
| TRANSACTION_AMOUNT | DECIMAL(15,2) | NOT NULL |
| CURRENCY_CODE | CHAR(3) | NOT CASESPECIFIC |
| MERCHANT_ID | VARCHAR(20) | nullable |
| MERCHANT_NAME | VARCHAR(100) | NOT CASESPECIFIC |
| MERCHANT_CATEGORY | VARCHAR(4) | nullable |
| COUNTERPARTY_ACCT | VARCHAR(20) | nullable |
| REFERENCE_NUMBER | VARCHAR(30) | nullable |
| DESCRIPTION_TEXT | VARCHAR(200) | NOT CASESPECIFIC |
| POSTING_DATE | DATE | nullable |
| VALUE_DATE | DATE | nullable |
| LOAD_DATE | DATE | NOT NULL |

## STG_CUSTOMER

Consumer: `dml/stored_procedures/sp_customer_scd2.sql`: compared/inserted stg attributes; types from DIM_CUSTOMER (no audit or onboarding columns are read from staging).

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| CUSTOMER_ID | INTEGER | NOT NULL |
| FIRST_NAME | VARCHAR(50) | NOT CASESPECIFIC NOT NULL |
| LAST_NAME | VARCHAR(50) | NOT CASESPECIFIC NOT NULL |
| DATE_OF_BIRTH | DATE | nullable |
| GENDER | CHAR(1) | nullable |
| MARITAL_STATUS | CHAR(1) | nullable |
| EMAIL_ADDRESS | VARCHAR(100) | NOT CASESPECIFIC  |
| PHONE_NUMBER | VARCHAR(20) | nullable |
| ADDRESS_LINE_1 | VARCHAR(100) | NOT CASESPECIFIC  |
| ADDRESS_LINE_2 | VARCHAR(100) | NOT CASESPECIFIC  |
| CITY | VARCHAR(50) | NOT CASESPECIFIC  |
| STATE_PROVINCE | VARCHAR(50) | NOT CASESPECIFIC  |
| POSTAL_CODE | VARCHAR(10) | nullable |
| COUNTRY_CODE | CHAR(3) | NOT CASESPECIFIC  |
| CUSTOMER_SEGMENT | VARCHAR(20) | NOT CASESPECIFIC  |
| RISK_SCORE | DECIMAL(5,2) | nullable |
| CREDIT_RATING | CHAR(3) | nullable |
| KYC_STATUS | VARCHAR(15) | NOT CASESPECIFIC  |

## STG_TRANSACTION_ERRORS

Consumer: `dml/stored_procedures/sp_load_daily_transactions.sql`: positional SELECT stg.*, 'INVALID_ACCOUNT', p_batch_id. Column order must be identical to staging before the two appended fields.

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| TRANSACTION_ID | BIGINT | NOT NULL |
| ACCOUNT_ID | VARCHAR(20) | NOT NULL |
| TRANSACTION_DATE | DATE | NOT NULL |
| TRANSACTION_TIME | TIME(0) | nullable |
| TRANSACTION_TYPE | VARCHAR(20) | NOT CASESPECIFIC NOT NULL |
| TRANSACTION_SUBTYPE | VARCHAR(30) | NOT CASESPECIFIC |
| CHANNEL | VARCHAR(20) | NOT CASESPECIFIC |
| TRANSACTION_AMOUNT | DECIMAL(15,2) | NOT NULL |
| CURRENCY_CODE | CHAR(3) | NOT CASESPECIFIC |
| MERCHANT_ID | VARCHAR(20) | nullable |
| MERCHANT_NAME | VARCHAR(100) | NOT CASESPECIFIC |
| MERCHANT_CATEGORY | VARCHAR(4) | nullable |
| COUNTERPARTY_ACCT | VARCHAR(20) | nullable |
| REFERENCE_NUMBER | VARCHAR(30) | nullable |
| DESCRIPTION_TEXT | VARCHAR(200) | NOT CASESPECIFIC |
| POSTING_DATE | DATE | nullable |
| VALUE_DATE | DATE | nullable |
| LOAD_DATE | DATE | NOT NULL |
| ERROR_REASON | VARCHAR(50) | nullable |
| BATCH_ID | BIGINT | nullable |

## ETL_BATCH_CONTROL

Consumer: `dml/scripts/bteq_daily_load.btq`: MAX(BATCH_ID)+1, completed/failed INSERT. Status length accommodates both literals.

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| BATCH_ID | BIGINT | NOT NULL |
| BATCH_DATE | DATE | nullable |
| BATCH_STATUS | VARCHAR(20) | nullable |
| START_TS | TIMESTAMP(0) | nullable |
| END_TS | TIMESTAMP(0) | nullable |

## ETL_LOG

Consumer: `dml/stored_procedures/sp_load_daily_transactions.sql`: start/completion/error INSERT. Message/name sizes are conservative capacity assumptions, not known legacy declarations.

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| PROCEDURE_NAME | VARCHAR(128) | nullable |
| BATCH_ID | BIGINT | nullable |
| LOG_LEVEL | VARCHAR(10) | nullable |
| LOG_MESSAGE | VARCHAR(2000) | nullable |
| LOG_TS | TIMESTAMP(0) | nullable |

## DIM_EXCHANGE_RATES

Consumer: `dml/stored_procedures/sp_load_daily_transactions.sql`: left join on currency pair/date and projected EXCHANGE_RATE; scale from FACT_TRANSACTION.

| Column (in physical order) | Teradata type | Attributes |
|---|---|---|
| FROM_CURRENCY | CHAR(3) | NOT CASESPECIFIC NOT NULL |
| TO_CURRENCY | CHAR(3) | NOT CASESPECIFIC NOT NULL |
| RATE_DATE | DATE | NOT NULL |
| EXCHANGE_RATE | DECIMAL(12,6) | nullable |
