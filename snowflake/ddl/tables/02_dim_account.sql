/**********************************************************************
 * DIM_ACCOUNT -- Account Dimension (Snowflake)
 *
 * Converted from Teradata MULTISET table.
 * - MULTISET removed (Snowflake default)
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - GENERATED ALWAYS AS IDENTITY  ->  AUTOINCREMENT
 * - NOT CASESPECIFIC removed (Snowflake default collation)
 * - FORMAT clause removed
 * - COMPRESS removed (automatic in Snowflake)
 * - BYTEINT  ->  SMALLINT
 * - UNIQUE PRIMARY INDEX  ->  PRIMARY KEY constraint
 * - Secondary indexes  ->  noted as comments
 * - PPI on OPENING_DATE  ->  CLUSTER BY
 * - COLLECT STATISTICS removed
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_ACCOUNT
(
    ACCOUNT_KEY         BIGINT           NOT NULL AUTOINCREMENT START 1 INCREMENT 1,
    ACCOUNT_ID          VARCHAR(20)      NOT NULL,
    CUSTOMER_ID         INTEGER          NOT NULL,
    ACCOUNT_TYPE        VARCHAR(20)      NOT NULL,
    ACCOUNT_SUBTYPE     VARCHAR(30),
    CURRENCY_CODE       CHAR(3)          DEFAULT 'NOK',
    OPENING_DATE        DATE             NOT NULL,
    CLOSING_DATE        DATE,
    ACCOUNT_STATUS      VARCHAR(15)      DEFAULT 'ACTIVE',
    INTEREST_RATE       DECIMAL(7,4),
    CREDIT_LIMIT        DECIMAL(15,2),
    OVERDRAFT_LIMIT     DECIMAL(15,2)    DEFAULT 0,
    BRANCH_ID           INTEGER,
    RELATIONSHIP_MGR_ID INTEGER,
    PRODUCT_ID          INTEGER          NOT NULL,
    IS_JOINT_ACCOUNT    SMALLINT         DEFAULT 0,
    TAX_REPORTING_FLAG  SMALLINT         DEFAULT 1,
    EFFECTIVE_FROM      TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    EFFECTIVE_TO        TIMESTAMP_NTZ(0) DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0),
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    ETL_UPDATE_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),

    -- Primary key (was Teradata UNIQUE PRIMARY INDEX UPI_ACCOUNT_KEY)
    CONSTRAINT PK_DIM_ACCOUNT PRIMARY KEY (ACCOUNT_KEY)
)
-- Clustering key replaces Teradata PPI on OPENING_DATE (yearly partitions)
CLUSTER BY (OPENING_DATE)
COMMENT = 'Account dimension with SCD Type 2 tracking for status and rate changes'
;

/*
 * Original Teradata secondary indexes (informational only):
 *   INDEX NUPI_ACCOUNT_ID (ACCOUNT_ID)
 *   INDEX IDX_ACCT_CUSTOMER (CUSTOMER_ID)
 *   INDEX IDX_ACCT_TYPE (ACCOUNT_TYPE)
 *   INDEX IDX_ACCT_BRANCH (BRANCH_ID)
 *
 * Snowflake does not support secondary indexes.
 * Consider search optimization service for frequently filtered columns.
 */
