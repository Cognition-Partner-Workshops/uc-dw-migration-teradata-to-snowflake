/**********************************************************************
 * DIM_PRODUCT — Banking Product Dimension (Snowflake)
 *
 * Converted from Teradata SET table.
 * - SET → removed
 * - NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO → removed
 * - BYTEINT → SMALLINT
 * - NOT CASESPECIFIC → COLLATE 'en-ci'
 * - FORMAT → removed
 * - COMPRESS → removed (automatic in Snowflake)
 * - UNIQUE PRIMARY INDEX / secondary indexes → removed
 * - COLLECT STATISTICS → removed
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_PRODUCT
(
    PRODUCT_ID          INTEGER          NOT NULL,
    PRODUCT_CODE        VARCHAR(20)      NOT NULL,
    PRODUCT_NAME        VARCHAR(100)     COLLATE 'en-ci' NOT NULL,
    PRODUCT_CATEGORY    VARCHAR(30)      COLLATE 'en-ci' NOT NULL,
    PRODUCT_SUBCATEGORY VARCHAR(50)      COLLATE 'en-ci',
    BASE_INTEREST_RATE  DECIMAL(7,4),
    MIN_BALANCE         DECIMAL(15,2)    DEFAULT 0,
    MAX_BALANCE         DECIMAL(15,2),
    FEE_STRUCTURE       VARCHAR(20),
    MONTHLY_FEE         DECIMAL(10,2)    DEFAULT 0,
    IS_REGULATED        SMALLINT         DEFAULT 1,
    REGULATORY_CODE     VARCHAR(20),
    LAUNCH_DATE         DATE,
    DISCONTINUE_DATE    DATE,
    IS_ACTIVE           SMALLINT         DEFAULT 1,
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Banking product catalog dimension';
