/**********************************************************************
 * FACT_MONTHLY_ACCOUNT_SNAPSHOT -- Month-End Balance Snapshot (Snowflake)
 *
 * Source: Teradata MULTISET table with PPI on SNAPSHOT_DATE
 *         (monthly intervals), COMPRESS, FORMAT.
 *
 * Conversion notes:
 *   - MULTISET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - SMALLINT COMPRESS 0 simplified to SMALLINT.
 *   - PRIMARY INDEX (non-unique) on (ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)
 *     has no direct equivalent; CLUSTER BY on SNAPSHOT_DATE used.
 *   - PPI monthly range partitions replaced by CLUSTER BY.
 *   - NO RANGE catch-all partition removed (not needed in Snowflake).
 *   - COLLECT STATISTICS removed.
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
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
)
CLUSTER BY (SNAPSHOT_DATE)
;

-- Original Teradata indexes (not supported in Snowflake):
--   PRIMARY INDEX PI_MONTHLY_SNAP (ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)

COMMENT ON TABLE BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT IS 'Monthly periodic snapshot: one row per account per calendar month';
