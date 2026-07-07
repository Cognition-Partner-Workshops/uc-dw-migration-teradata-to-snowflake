/**********************************************************************
 * DIM_CUSTOMER — Customer Dimension  (Snowflake)
 * Converted from Teradata SET table.
 *   - SET/NO FALLBACK/JOURNAL/CHECKSUM/MERGEBLOCKRATIO removed
 *   - GENERATED ALWAYS AS IDENTITY -> IDENTITY(1,1)
 *   - NOT CASESPECIFIC -> COLLATE 'en-ci' (preserves case-insensitive compares)
 *   - COMPRESS clauses removed (Snowflake auto-compresses)
 *   - DATE FORMAT '...' removed (formatting is a query/view concern)
 *   - UNIQUE PRIMARY INDEX -> PRIMARY KEY (declared, not enforced) + CLUSTER BY
 *   - Secondary INDEX / PARTITION BY RANGE_N -> CLUSTER BY on onboarding date
 *   - COLLECT STATISTICS removed (automatic in Snowflake)
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_CUSTOMER
(
    CUSTOMER_ID         INTEGER          NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL IDENTITY(1,1),
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
    EFFECTIVE_FROM      TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),
    EFFECTIVE_TO        TIMESTAMP_NTZ(0) DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ,
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),
    ETL_UPDATE_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_KEY)
)
CLUSTER BY (ONBOARDING_DATE);
-- Teradata secondary indexes NUPI_CUSTOMER_ID / IDX_CUST_SEGMENT / IDX_CUST_COUNTRY
-- have no Snowflake equivalent; micro-partition pruning handles these access paths.

COMMENT ON TABLE BANKING_DW.DIM_CUSTOMER IS 'SCD Type 2 customer dimension with KYC and risk attributes';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_KEY IS 'Surrogate key for SCD Type 2';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_ID IS 'Natural key from source system';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.KYC_STATUS IS 'Know Your Customer verification status';
