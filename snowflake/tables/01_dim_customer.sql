/**********************************************************************
 * DIM_CUSTOMER -- Customer Dimension (Snowflake)
 *
 * Source: Teradata SET table with PRIMARY INDEX, COMPRESS, FORMAT,
 *         CASESPECIFIC, PARTITION BY RANGE_N, GENERATED ALWAYS AS IDENTITY.
 *
 * Conversion notes:
 *   - SET table / physical attributes (FALLBACK, JOURNAL, CHECKSUM,
 *     MERGEBLOCKRATIO) removed; not applicable in Snowflake.
 *   - COMPRESS clauses removed; Snowflake applies automatic compression.
 *   - NOT CASESPECIFIC removed; Snowflake string comparisons are
 *     case-insensitive by default (depends on collation).
 *   - FORMAT 'YYYY-MM-DD' removed; Snowflake uses native DATE display.
 *   - BYTEINT converted to SMALLINT (Snowflake has no BYTEINT).
 *   - GENERATED ALWAYS AS IDENTITY converted to AUTOINCREMENT.
 *   - UNIQUE PRIMARY INDEX converted to PRIMARY KEY constraint.
 *   - Secondary indexes (NUPI, named indexes) converted to separate
 *     comments; Snowflake does not support traditional B-tree indexes.
 *   - PARTITION BY RANGE_N on ONBOARDING_DATE converted to CLUSTER BY.
 *   - COLLECT STATISTICS removed; Snowflake auto-manages statistics.
 *   - COMMENT ON syntax retained (Snowflake-compatible).
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
    EFFECTIVE_FROM      TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    EFFECTIVE_TO        TIMESTAMP_NTZ(0) DEFAULT '9999-12-31 23:59:59'::TIMESTAMP_NTZ(0),
    CURRENT_FLAG        CHAR(1)          DEFAULT 'Y',
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),
    ETL_UPDATE_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),

    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_KEY)
)
CLUSTER BY (ONBOARDING_DATE)
;

-- Secondary indexes are not supported in Snowflake.
-- Original Teradata indexes preserved as documentation:
--   INDEX NUPI_CUSTOMER_ID  (CUSTOMER_ID)
--   INDEX IDX_CUST_SEGMENT  (CUSTOMER_SEGMENT)
--   INDEX IDX_CUST_COUNTRY  (COUNTRY_CODE)
-- Consider search optimization service for frequently filtered columns.

COMMENT ON TABLE BANKING_DW.DIM_CUSTOMER IS 'SCD Type 2 customer dimension with KYC and risk attributes';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_KEY IS 'Surrogate key for SCD Type 2';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.CUSTOMER_ID IS 'Natural key from source system';
COMMENT ON COLUMN BANKING_DW.DIM_CUSTOMER.KYC_STATUS IS 'Know Your Customer verification status';
