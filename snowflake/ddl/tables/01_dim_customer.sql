/**********************************************************************
 * DIM_CUSTOMER -- Customer Dimension (Snowflake)
 *
 * Converted from Teradata SET TABLE.
 * Key changes:
 *   - Removed SET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - BYTEINT -> SMALLINT (Snowflake has no BYTEINT)
 *   - COMPRESS clauses removed (Snowflake compresses automatically)
 *   - NOT CASESPECIFIC removed; added COLLATE 'en-ci' for
 *     case-insensitive columns
 *   - FORMAT on DATE columns removed (use TO_CHAR in queries)
 *   - GENERATED ALWAYS AS IDENTITY -> IDENTITY (AUTOINCREMENT)
 *   - UNIQUE PRIMARY INDEX -> PRIMARY KEY constraint
 *   - Secondary indexes -> standalone CREATE INDEX (Snowflake currently
 *     does not enforce indexes but they can be declared)
 *   - PARTITION BY RANGE_N -> CLUSTER BY on the partition column
 *   - COLLECT STATISTICS removed (Snowflake manages stats automatically)
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_CUSTOMER
(
    CUSTOMER_ID         INTEGER          NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL AUTOINCREMENT START 1 INCREMENT 1,
    FIRST_NAME          VARCHAR(50)      COLLATE 'en-ci' NOT NULL,
    LAST_NAME           VARCHAR(50)      COLLATE 'en-ci' NOT NULL,
    DATE_OF_BIRTH       DATE,
    GENDER              CHAR(1),
    MARITAL_STATUS      CHAR(1),
    EMAIL_ADDRESS       VARCHAR(100)     COLLATE 'en-ci',
    PHONE_NUMBER        VARCHAR(20),
    ADDRESS_LINE_1      VARCHAR(100)     COLLATE 'en-ci',
    ADDRESS_LINE_2      VARCHAR(100)     COLLATE 'en-ci',
    CITY                VARCHAR(50)      COLLATE 'en-ci',
    STATE_PROVINCE      VARCHAR(50)      COLLATE 'en-ci',
    POSTAL_CODE         VARCHAR(10),
    COUNTRY_CODE        CHAR(3)          COLLATE 'en-ci' DEFAULT 'NOR',
    CUSTOMER_SEGMENT    VARCHAR(20)      COLLATE 'en-ci',
    RISK_SCORE          DECIMAL(5,2),
    CREDIT_RATING       CHAR(3),
    KYC_STATUS          VARCHAR(15)      COLLATE 'en-ci' DEFAULT 'PENDING',
    ONBOARDING_DATE     DATE             NOT NULL,
    LAST_REVIEW_DATE    DATE,
    IS_ACTIVE           SMALLINT         DEFAULT 1,
    EFFECTIVE_FROM      TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    EFFECTIVE_TO        TIMESTAMP_NTZ(0) DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0),
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    ETL_UPDATE_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),

    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_KEY)
)
CLUSTER BY (ONBOARDING_DATE)
COMMENT = 'SCD Type 2 customer dimension with KYC and risk attributes';

-- Column comments
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_KEY IS 'Surrogate key for SCD Type 2';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_ID IS 'Natural key from source system';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.KYC_STATUS IS 'Know Your Customer verification status';
