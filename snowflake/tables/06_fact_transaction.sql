/**********************************************************************
 * FACT_TRANSACTION -- Daily Transaction Fact Table (Snowflake)
 *
 * Source: Teradata MULTISET table with Partitioned Primary Index (PPI)
 *         on TRANSACTION_DATE (monthly partitions), COMPRESS,
 *         CASESPECIFIC, FORMAT.
 *
 * Conversion notes:
 *   - MULTISET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - NOT CASESPECIFIC removed.
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - BYTEINT converted to SMALLINT.
 *   - PRIMARY INDEX (non-unique) has no direct Snowflake equivalent;
 *     converted to CLUSTER BY for query performance.
 *   - PPI on TRANSACTION_DATE (monthly intervals) converted to
 *     CLUSTER BY (TRANSACTION_DATE) for micro-partition pruning.
 *   - NO RANGE catch-all partition removed (not needed in Snowflake).
 *   - COLLECT STATISTICS removed.
 *   - TIME(0) converted to TIME (Snowflake TIME supports precision).
 *   - TIMESTAMP(6) kept as-is (Snowflake supports up to 9).
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.FACT_TRANSACTION
(
    TRANSACTION_ID      BIGINT           NOT NULL,
    TRANSACTION_DATE    DATE             NOT NULL,
    TRANSACTION_TIME    TIME(0),
    TRANSACTION_TS      TIMESTAMP_NTZ(6),
    ACCOUNT_KEY         BIGINT           NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL,
    PRODUCT_ID          INTEGER          NOT NULL,
    BRANCH_ID           INTEGER,
    DATE_KEY            INTEGER          NOT NULL,
    TRANSACTION_TYPE    VARCHAR(20)      NOT NULL,
    TRANSACTION_SUBTYPE VARCHAR(30),
    CHANNEL             VARCHAR(20),
    TRANSACTION_AMOUNT  DECIMAL(15,2)    NOT NULL,
    TRANSACTION_CURRENCY CHAR(3)         DEFAULT 'NOK',
    BASE_CURRENCY_AMOUNT DECIMAL(15,2),
    EXCHANGE_RATE       DECIMAL(12,6)    DEFAULT 1.000000,
    RUNNING_BALANCE     DECIMAL(15,2),
    MERCHANT_ID         VARCHAR(20),
    MERCHANT_NAME       VARCHAR(100),
    MERCHANT_CATEGORY   VARCHAR(4),       -- MCC code
    COUNTERPARTY_ACCT   VARCHAR(20),
    REFERENCE_NUMBER    VARCHAR(30),
    DESCRIPTION_TEXT    VARCHAR(200),
    IS_INTERNATIONAL    SMALLINT         DEFAULT 0,
    IS_FLAGGED          SMALLINT         DEFAULT 0,
    FLAG_REASON         VARCHAR(50),
    POSTING_DATE        DATE,
    VALUE_DATE          DATE,
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
)
CLUSTER BY (TRANSACTION_DATE)
;

-- Original Teradata indexes (not supported in Snowflake):
--   PRIMARY INDEX PI_FACT_TXN (ACCOUNT_KEY, TRANSACTION_DATE)
-- The CLUSTER BY on TRANSACTION_DATE provides partition pruning
-- equivalent to the Teradata PPI monthly range partitions.

COMMENT ON TABLE BANKING_DW.FACT_TRANSACTION IS 'Grain: one row per transaction. Clustered on TRANSACTION_DATE for micro-partition pruning (replaces Teradata PPI).';
