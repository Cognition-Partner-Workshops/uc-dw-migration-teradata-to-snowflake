/**********************************************************************
 * FACT_TRANSACTION — Daily Transaction Fact Table (Snowflake)
 * Converted from Teradata MULTISET table with PPI
 * Changes:
 *   - Removed MULTISET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - Removed COMPRESS clauses
 *   - Removed NOT CASESPECIFIC
 *   - Removed FORMAT on DATE/TIME columns
 *   - Replaced BYTEINT with SMALLINT
 *   - Replaced Teradata PPI (PARTITION BY RANGE_N) with CLUSTER BY
 *   - Removed PRIMARY INDEX; using CLUSTER BY for query performance
 *   - Removed COLLECT STATISTICS
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.FACT_TRANSACTION
(
    TRANSACTION_ID      BIGINT           NOT NULL,
    TRANSACTION_DATE    DATE             NOT NULL,
    TRANSACTION_TIME    TIME,
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
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY)
COMMENT = 'Grain: one row per transaction. Clustered on TRANSACTION_DATE for partition elimination.';
