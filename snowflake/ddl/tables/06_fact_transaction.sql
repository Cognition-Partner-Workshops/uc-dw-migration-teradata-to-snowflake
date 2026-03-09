/**********************************************************************
 * FACT_TRANSACTION -- Daily Transaction Fact Table (Snowflake)
 *
 * Converted from Teradata MULTISET table with PPI.
 * - MULTISET removed (Snowflake default)
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - NOT CASESPECIFIC removed
 * - FORMAT clause removed
 * - COMPRESS removed (automatic in Snowflake)
 * - BYTEINT  ->  SMALLINT
 * - PRIMARY INDEX PI_FACT_TXN  ->  noted as comment
 * - PPI on TRANSACTION_DATE (monthly)  ->  CLUSTER BY (TRANSACTION_DATE)
 * - COLLECT STATISTICS removed
 * - TIME(0) kept (Snowflake supports TIME natively)
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
-- Clustering key replaces Teradata PPI on TRANSACTION_DATE (monthly partitions)
-- Also includes ACCOUNT_KEY to mirror the original Primary Index distribution
CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)
COMMENT = 'Grain: one row per transaction. Clustered on TRANSACTION_DATE for partition-elimination-like pruning.'
;

/*
 * Original Teradata indexes (informational only):
 *   PRIMARY INDEX PI_FACT_TXN (ACCOUNT_KEY, TRANSACTION_DATE)
 *   PPI: PARTITION BY RANGE_N(TRANSACTION_DATE BETWEEN '2018-01-01' AND '2030-12-31' EACH INTERVAL '1' MONTH, NO RANGE)
 *
 * Snowflake micro-partitioning with CLUSTER BY achieves similar query pruning.
 */
