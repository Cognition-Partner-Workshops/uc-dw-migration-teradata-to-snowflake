/**********************************************************************
 * DIM_CUSTOMER -- Customer Dimension (Snowflake)
 * Converted from Teradata SET table
 * - Removed: SET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 * - Removed: COMPRESS clauses (Snowflake auto-compresses)
 * - Removed: NOT CASESPECIFIC (Snowflake is case-sensitive by default)
 * - Removed: FORMAT on column definitions
 * - Replaced: BYTEINT -> SMALLINT
 * - Replaced: GENERATED ALWAYS AS IDENTITY -> AUTOINCREMENT
 * - Replaced: UPI -> PRIMARY KEY
 * - Removed: Secondary indexes (NUPI, IDX_*)
 * - Replaced: PARTITION BY RANGE_N -> CLUSTER BY
 * - Removed: COLLECT STATISTICS
 **********************************************************************/

CREATE TABLE BANKING_DW.DIM_CUSTOMER
(
    CUSTOMER_ID         INTEGER          NOT NULL,
    CUSTOMER_KEY        BIGINT           NOT NULL AUTOINCREMENT START 1 INCREMENT 1,
    -- Note: Snowflake is case-sensitive by default. Use COLLATE 'en-ci' or UPPER()/LOWER() where case-insensitive comparison is needed.
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
    EFFECTIVE_FROM      TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),
    EFFECTIVE_TO        TIMESTAMP_NTZ(0) DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ,
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),
    ETL_UPDATE_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (CUSTOMER_KEY)
)
-- Note: Secondary indexes (NUPI_CUSTOMER_ID, IDX_CUST_SEGMENT, IDX_CUST_COUNTRY) removed.
-- Snowflake does not support user-created indexes. Consider clustering keys if query performance warrants.
CLUSTER BY (ONBOARDING_DATE);

COMMENT ON TABLE BANKING_DW.DIM_CUSTOMER IS 'SCD Type 2 customer dimension with KYC and risk attributes';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_KEY IS 'Surrogate key for SCD Type 2';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_ID IS 'Natural key from source system';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.KYC_STATUS IS 'Know Your Customer verification status';
