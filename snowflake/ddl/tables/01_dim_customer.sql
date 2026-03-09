/**********************************************************************
 * DIM_CUSTOMER -- Customer Dimension (Snowflake)
 *
 * Converted from Teradata SET table.
 * - SET table semantics removed (Snowflake tables are always MULTISET)
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - GENERATED ALWAYS AS IDENTITY  ->  AUTOINCREMENT
 * - NOT CASESPECIFIC removed (Snowflake default collation is case-insensitive)
 * - FORMAT clause removed (use display formatting at query time)
 * - COMPRESS removed (Snowflake applies automatic compression)
 * - BYTEINT  ->  SMALLINT (no BYTEINT in Snowflake)
 * - UNIQUE PRIMARY INDEX  ->  PRIMARY KEY constraint
 * - Secondary indexes  ->  noted as comments (no secondary indexes in Snowflake)
 * - PPI on ONBOARDING_DATE  ->  CLUSTER BY
 * - COLLECT STATISTICS removed (Snowflake auto-collects statistics)
 * - COMMENT ON  ->  Snowflake COMMENT syntax
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

    -- Primary key (was Teradata UNIQUE PRIMARY INDEX UPI_CUSTOMER_KEY)
    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY (CUSTOMER_KEY)
)
-- Clustering key replaces Teradata PPI on ONBOARDING_DATE (yearly partitions)
CLUSTER BY (ONBOARDING_DATE)
COMMENT = 'SCD Type 2 customer dimension with KYC and risk attributes'
;

-- Column-level comments
ALTER TABLE BANKING_DW.DIM_CUSTOMER ALTER COLUMN CUSTOMER_KEY COMMENT 'Surrogate key for SCD Type 2';
ALTER TABLE BANKING_DW.DIM_CUSTOMER ALTER COLUMN CUSTOMER_ID COMMENT 'Natural key from source system';
ALTER TABLE BANKING_DW.DIM_CUSTOMER ALTER COLUMN KYC_STATUS COMMENT 'Know Your Customer verification status';

/*
 * Original Teradata secondary indexes (informational only):
 *   INDEX NUPI_CUSTOMER_ID (CUSTOMER_ID)
 *   INDEX IDX_CUST_SEGMENT (CUSTOMER_SEGMENT)
 *   INDEX IDX_CUST_COUNTRY (COUNTRY_CODE)
 *
 * Snowflake does not support secondary indexes.
 * Consider search optimization service for frequently filtered columns.
 */
