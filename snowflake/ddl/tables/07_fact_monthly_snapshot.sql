/**********************************************************************
 * FACT_MONTHLY_ACCOUNT_SNAPSHOT — Month-End Balance Snapshot (Snowflake)
 * Converted from Teradata MULTISET table with PPI
 * Changes:
 *   - Removed MULTISET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - Removed COMPRESS clauses
 *   - Removed FORMAT on DATE columns
 *   - Replaced BYTEINT/SMALLINT COMPRESS with SMALLINT
 *   - Replaced Teradata PPI (PARTITION BY RANGE_N) with CLUSTER BY
 *   - Removed PRIMARY INDEX; using CLUSTER BY for query performance
 *   - Removed COLLECT STATISTICS
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT
(
    SNAPSHOT_DATE       DATE             NOT NULL,
    SNAPSHOT_MONTH_KEY  INTEGER          NOT NULL,   -- YYYYMM format
    ACCOUNT_KEY         BIGINT           NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL,
    PRODUCT_ID          INTEGER          NOT NULL,
    BRANCH_ID           INTEGER,
    OPENING_BALANCE     DECIMAL(15,2)    NOT NULL,
    CLOSING_BALANCE     DECIMAL(15,2)    NOT NULL,
    AVERAGE_BALANCE     DECIMAL(15,2),
    MINIMUM_BALANCE     DECIMAL(15,2),
    MAXIMUM_BALANCE     DECIMAL(15,2),
    TOTAL_DEBITS        DECIMAL(15,2)    DEFAULT 0,
    TOTAL_CREDITS       DECIMAL(15,2)    DEFAULT 0,
    DEBIT_COUNT         INTEGER          DEFAULT 0,
    CREDIT_COUNT        INTEGER          DEFAULT 0,
    INTEREST_EARNED     DECIMAL(12,2)    DEFAULT 0,
    INTEREST_CHARGED    DECIMAL(12,2)    DEFAULT 0,
    FEES_CHARGED        DECIMAL(12,2)    DEFAULT 0,
    DAYS_IN_OVERDRAFT   SMALLINT         DEFAULT 0,
    DAYS_DORMANT        SMALLINT         DEFAULT 0,
    CURRENCY_CODE       CHAR(3)          DEFAULT 'NOK',
    BASE_CURRENCY_CLOSING DECIMAL(15,2),
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (SNAPSHOT_DATE, ACCOUNT_KEY)
COMMENT = 'Monthly periodic snapshot: one row per account per calendar month';
