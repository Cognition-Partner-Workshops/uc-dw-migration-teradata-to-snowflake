/**********************************************************************
 * DIM_CUSTOMER — Customer Dimension (Snowflake)
 * Converted from Teradata SET table
 * Changes:
 *   - Removed SET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - Removed COMPRESS clauses (Snowflake compresses automatically)
 *   - Removed NOT CASESPECIFIC (use COLLATE 'en-ci' or handle in queries)
 *   - Removed FORMAT on DATE columns (use TO_CHAR in queries)
 *   - Replaced BYTEINT with BOOLEAN or SMALLINT
 *   - Replaced GENERATED ALWAYS AS IDENTITY with AUTOINCREMENT
 *   - Replaced PRIMARY INDEX / PARTITION BY RANGE_N with CLUSTER BY
 *   - Removed COLLECT STATISTICS (Snowflake handles automatically)
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_CUSTOMER
(
    CUSTOMER_ID         INTEGER          NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL AUTOINCREMENT START 1 INCREMENT 1,
    FIRST_NAME          VARCHAR(50)      NOT NULL,
    LAST_NAME           VARCHAR(50)      NOT NULL,
    DATE_OF_BIRTH       DATE,
    GENDER              CHAR(1),
    MARITAL_STATUS      CHAR(1),
    EMAIL_ADDRESS       VARCHAR(100),
    PHONE_NUMBER        VARCHAR(20),
    ADDRESS_LINE_1      VARCHAR(100),
    ADDRESS_LINE_2      VARCHAR(100),
    CITY                VARCHAR(50),
    STATE_PROVINCE      VARCHAR(50),
    POSTAL_CODE         VARCHAR(10),
    COUNTRY_CODE        CHAR(3)          DEFAULT 'NOR',
    CUSTOMER_SEGMENT    VARCHAR(20),
    RISK_SCORE          DECIMAL(5,2),
    CREDIT_RATING       CHAR(3),
    KYC_STATUS          VARCHAR(15)      DEFAULT 'PENDING',
    ONBOARDING_DATE     DATE             NOT NULL,
    LAST_REVIEW_DATE    DATE,
    IS_ACTIVE           SMALLINT         DEFAULT 1,
    EFFECTIVE_FROM      TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),
    EFFECTIVE_TO        TIMESTAMP_NTZ    DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ,
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),
    ETL_UPDATE_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_KEY)
)
CLUSTER BY (ONBOARDING_DATE)
COMMENT = 'SCD Type 2 customer dimension with KYC and risk attributes';

-- Column comments
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_KEY IS 'Surrogate key for SCD Type 2';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_ID IS 'Natural key from source system';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.KYC_STATUS IS 'Know Your Customer verification status';
