/**********************************************************************
 * DIM_ACCOUNT — Account Dimension (Snowflake)
 * Converted from Teradata MULTISET table
 * Changes:
 *   - Removed MULTISET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - Removed COMPRESS clauses
 *   - Removed NOT CASESPECIFIC
 *   - Removed FORMAT on DATE columns
 *   - Replaced BYTEINT with SMALLINT
 *   - Replaced GENERATED ALWAYS AS IDENTITY with AUTOINCREMENT
 *   - Replaced PRIMARY INDEX / PARTITION BY RANGE_N with CLUSTER BY
 *   - Removed COLLECT STATISTICS
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
    EFFECTIVE_FROM      TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),
    EFFECTIVE_TO        TIMESTAMP_NTZ    DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ,
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),
    ETL_UPDATE_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT PK_DIM_ACCOUNT PRIMARY KEY (ACCOUNT_KEY)
)
CLUSTER BY (OPENING_DATE)
COMMENT = 'Account dimension with SCD Type 2 tracking for status and rate changes';
