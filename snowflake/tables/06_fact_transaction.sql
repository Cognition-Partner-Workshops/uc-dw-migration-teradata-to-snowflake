/**********************************************************************
 * FACT_TRANSACTION — Daily Transaction Fact Table (Snowflake)
 *
 * Converted from Teradata MULTISET table with Partitioned Primary Index.
 * - MULTISET → removed
 * - NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO → removed
 * - BYTEINT → SMALLINT
 * - NOT CASESPECIFIC → COLLATE 'en-ci'
 * - FORMAT → removed
 * - COMPRESS → removed (automatic in Snowflake)
 * - PRIMARY INDEX (non-unique) → removed
 * - PPI RANGE_N with NO RANGE → CLUSTER BY for micro-partition pruning
 * - COLLECT STATISTICS → removed
 * - TIME(0) → TIME(0) (supported in Snowflake)
 * - TIMESTAMP(6) → TIMESTAMP_NTZ(6)
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
    TRANSACTION_TYPE    VARCHAR(20)      COLLATE 'en-ci' NOT NULL,
    TRANSACTION_SUBTYPE VARCHAR(30)      COLLATE 'en-ci',
    CHANNEL             VARCHAR(20)      COLLATE 'en-ci',
    TRANSACTION_AMOUNT  DECIMAL(15,2)    NOT NULL,
    TRANSACTION_CURRENCY CHAR(3)         COLLATE 'en-ci' DEFAULT 'NOK',
    BASE_CURRENCY_AMOUNT DECIMAL(15,2),
    EXCHANGE_RATE       DECIMAL(12,6)    DEFAULT 1.000000,
    RUNNING_BALANCE     DECIMAL(15,2),
    MERCHANT_ID         VARCHAR(20),
    MERCHANT_NAME       VARCHAR(100)     COLLATE 'en-ci',
    MERCHANT_CATEGORY   VARCHAR(4),
    COUNTERPARTY_ACCT   VARCHAR(20),
    REFERENCE_NUMBER    VARCHAR(30),
    DESCRIPTION_TEXT    VARCHAR(200)     COLLATE 'en-ci',
    IS_INTERNATIONAL    SMALLINT         DEFAULT 0,
    IS_FLAGGED          SMALLINT         DEFAULT 0,
    FLAG_REASON         VARCHAR(50),
    POSTING_DATE        DATE,
    VALUE_DATE          DATE,
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)
COMMENT = 'Grain: one row per transaction. Clustered on TRANSACTION_DATE for partition pruning (replaces Teradata PPI).';
