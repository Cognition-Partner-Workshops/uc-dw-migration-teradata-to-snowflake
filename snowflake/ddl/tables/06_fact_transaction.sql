/**********************************************************************
 * FACT_TRANSACTION -- Daily Transaction Fact Table (Snowflake)
 * Converted from Teradata MULTISET table with PPI
 * - Removed: MULTISET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 * - Removed: COMPRESS clauses (Snowflake auto-compresses)
 * - Removed: NOT CASESPECIFIC (Snowflake is case-sensitive by default)
 * - Removed: FORMAT on column definitions
 * - Replaced: BYTEINT -> SMALLINT
 * - Added: TRANSACTION_ID as PRIMARY KEY
 * - Replaced: PPI PARTITION BY RANGE_N -> CLUSTER BY
 * - Removed: COLLECT STATISTICS
 **********************************************************************/

CREATE TABLE BANKING_DW.FACT_TRANSACTION
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
    -- Note: Snowflake is case-sensitive by default. Use COLLATE 'en-ci' or UPPER()/LOWER() where case-insensitive comparison is needed.
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
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (TRANSACTION_ID)
)
-- Note: Secondary indexes not applicable in Snowflake.
-- Clustering on TRANSACTION_DATE and ACCOUNT_KEY replaces the Teradata PPI for partition elimination.
CLUSTER BY (TRANSACTION_DATE, ACCOUNT_KEY);

COMMENT ON TABLE BANKING_DW.FACT_TRANSACTION IS 'Grain: one row per transaction. Clustered on TRANSACTION_DATE and ACCOUNT_KEY for partition elimination.';
