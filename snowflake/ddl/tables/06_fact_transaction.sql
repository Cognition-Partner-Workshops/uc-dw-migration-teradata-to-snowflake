/**********************************************************************
 * FACT_TRANSACTION -- Daily Transaction Fact Table (Snowflake)
 *
 * Converted from Teradata MULTISET table with PPI.
 * Changes:
 *   - Removed MULTISET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - PRIMARY INDEX -> removed (no PI concept in Snowflake)
 *   - PARTITION BY RANGE_N -> CLUSTER BY on partition key columns
 *   - COMPRESS clauses removed
 *   - NOT CASESPECIFIC -> COLLATE 'en-ci'
 *   - DATE FORMAT -> removed
 *   - BYTEINT -> SMALLINT
 *   - COLLECT STATISTICS -> removed
 *   - TIME(0) -> TIME(0) (compatible)
 *   - TIMESTAMP(6) -> TIMESTAMP_NTZ(6) (explicit timezone handling)
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
    MERCHANT_CATEGORY   VARCHAR(4),       -- MCC code
    COUNTERPARTY_ACCT   VARCHAR(20),
    REFERENCE_NUMBER    VARCHAR(30),
    DESCRIPTION_TEXT    VARCHAR(200)     COLLATE 'en-ci',
    IS_INTERNATIONAL    SMALLINT         DEFAULT 0,
    IS_FLAGGED          SMALLINT         DEFAULT 0,
    FLAG_REASON         VARCHAR(50),
    POSTING_DATE        DATE,
    VALUE_DATE          DATE,
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)
COMMENT = 'Grain: one row per transaction. Clustered on TRANSACTION_DATE for partition elimination.';

-- Original Teradata PI: PRIMARY INDEX PI_FACT_TXN (ACCOUNT_KEY, TRANSACTION_DATE)
-- Original Teradata PPI: PARTITION BY RANGE_N(TRANSACTION_DATE ... EACH INTERVAL 1 MONTH)
