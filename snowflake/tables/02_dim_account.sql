/**********************************************************************
 * DIM_ACCOUNT -- Account Dimension (Snowflake)
 *
 * Source: Teradata MULTISET table with composite primary index,
 *         COMPRESS, CASESPECIFIC, FORMAT, GENERATED ALWAYS AS IDENTITY,
 *         PARTITION BY RANGE_N.
 *
 * Conversion notes:
 *   - MULTISET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - NOT CASESPECIFIC removed.
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - BYTEINT converted to SMALLINT.
 *   - GENERATED ALWAYS AS IDENTITY converted to AUTOINCREMENT.
 *   - UNIQUE PRIMARY INDEX converted to PRIMARY KEY.
 *   - Secondary indexes documented as comments.
 *   - PARTITION BY RANGE_N on OPENING_DATE converted to CLUSTER BY.
 *   - COLLECT STATISTICS removed.
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

    CONSTRAINT PK_DIM_ACCOUNT PRIMARY KEY (ACCOUNT_KEY)
)
CLUSTER BY (OPENING_DATE)
;

-- Original Teradata secondary indexes (not supported in Snowflake):
--   INDEX NUPI_ACCOUNT_ID    (ACCOUNT_ID)
--   INDEX IDX_ACCT_CUSTOMER  (CUSTOMER_ID)
--   INDEX IDX_ACCT_TYPE      (ACCOUNT_TYPE)
--   INDEX IDX_ACCT_BRANCH    (BRANCH_ID)

COMMENT ON TABLE BANKING_DW.DIM_ACCOUNT IS 'Account dimension with SCD Type 2 tracking for status and rate changes';
