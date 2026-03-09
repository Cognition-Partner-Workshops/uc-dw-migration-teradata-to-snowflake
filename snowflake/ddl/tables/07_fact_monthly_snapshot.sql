/**********************************************************************
 * FACT_MONTHLY_ACCOUNT_SNAPSHOT -- Month-End Balance Snapshot (Snowflake)
 *
 * Periodic snapshot fact table, one row per account per month.
 * Converted from Teradata MULTISET table with PPI.
 * - MULTISET removed (Snowflake default)
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - FORMAT clause removed
 * - COMPRESS removed (automatic in Snowflake)
 * - BYTEINT  ->  SMALLINT (N/A here, no BYTEINT columns)
 * - PRIMARY INDEX  ->  noted as comment
 * - PPI on SNAPSHOT_DATE (monthly)  ->  CLUSTER BY
 * - COLLECT STATISTICS removed
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
-- Clustering key replaces Teradata PPI on SNAPSHOT_DATE (monthly partitions)
-- Also includes ACCOUNT_KEY to mirror the original Primary Index distribution
CLUSTER BY (SNAPSHOT_DATE, ACCOUNT_KEY)
COMMENT = 'Monthly periodic snapshot: one row per account per calendar month'
;

/*
 * Original Teradata indexes (informational only):
 *   PRIMARY INDEX PI_MONTHLY_SNAP (ACCOUNT_KEY, SNAPSHOT_MONTH_KEY)
 *   PPI: PARTITION BY RANGE_N(SNAPSHOT_DATE BETWEEN '2018-01-01' AND '2030-12-31' EACH INTERVAL '1' MONTH, NO RANGE)
 *
 * Snowflake micro-partitioning with CLUSTER BY achieves similar query pruning.
 */
