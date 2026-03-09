/**********************************************************************
 * DIM_PRODUCT -- Banking Product Dimension (Snowflake)
 *
 * Converted from Teradata SET table.
 * - SET table semantics removed
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - NOT CASESPECIFIC removed
 * - FORMAT clause removed
 * - COMPRESS removed (automatic in Snowflake)
 * - BYTEINT  ->  SMALLINT
 * - UNIQUE PRIMARY INDEX  ->  PRIMARY KEY constraint
 * - Secondary indexes  ->  noted as comments
 * - COLLECT STATISTICS removed
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_PRODUCT
(
    PRODUCT_ID          INTEGER          NOT NULL,
    PRODUCT_CODE        VARCHAR(20)      NOT NULL,
    PRODUCT_NAME        VARCHAR(100)     NOT NULL,
    PRODUCT_CATEGORY    VARCHAR(30)      NOT NULL,
    PRODUCT_SUBCATEGORY VARCHAR(50),
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
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),

    -- Primary key (was Teradata UNIQUE PRIMARY INDEX UPI_PRODUCT_ID)
    CONSTRAINT PK_DIM_PRODUCT PRIMARY KEY (PRODUCT_ID)
)
COMMENT = 'Banking product catalog dimension'
;

/*
 * Original Teradata secondary indexes (informational only):
 *   INDEX IDX_PROD_CODE (PRODUCT_CODE)
 *   INDEX IDX_PROD_CATEGORY (PRODUCT_CATEGORY)
 *
 * Snowflake does not support secondary indexes.
 * Consider search optimization service for frequently filtered columns.
 */
