/**********************************************************************
 * DIM_PRODUCT -- Banking Product Dimension (Snowflake)
 *
 * Source: Teradata SET table with single-column primary index,
 *         COMPRESS, CASESPECIFIC, FORMAT.
 *
 * Conversion notes:
 *   - SET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - NOT CASESPECIFIC removed.
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - BYTEINT converted to SMALLINT.
 *   - UNIQUE PRIMARY INDEX converted to PRIMARY KEY.
 *   - Secondary indexes documented as comments.
 *   - No partitioning in source; no CLUSTER BY needed (small table).
 *   - COLLECT STATISTICS removed.
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

    CONSTRAINT PK_DIM_PRODUCT PRIMARY KEY (PRODUCT_ID)
)
;

-- Original Teradata secondary indexes (not supported in Snowflake):
--   INDEX IDX_PROD_CODE      (PRODUCT_CODE)
--   INDEX IDX_PROD_CATEGORY  (PRODUCT_CATEGORY)

COMMENT ON TABLE BANKING_DW.DIM_PRODUCT IS 'Banking product catalog dimension';
