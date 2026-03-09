/**********************************************************************
 * DIM_PRODUCT -- Banking Product Dimension (Snowflake)
 * Converted from Teradata SET table
 * - Removed: SET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 * - Removed: COMPRESS clauses (Snowflake auto-compresses)
 * - Removed: NOT CASESPECIFIC (Snowflake is case-sensitive by default)
 * - Removed: FORMAT on column definitions
 * - Replaced: BYTEINT -> SMALLINT
 * - Replaced: UPI -> PRIMARY KEY
 * - Removed: Secondary indexes (IDX_*)
 * - Removed: COLLECT STATISTICS
 * - No clustering needed (small reference table)
 **********************************************************************/

CREATE TABLE BANKING_DW.DIM_PRODUCT
(
    PRODUCT_ID          INTEGER          NOT NULL,
    PRODUCT_CODE        VARCHAR(20)      NOT NULL,
    -- Note: Snowflake is case-sensitive by default. Use COLLATE 'en-ci' or UPPER()/LOWER() where case-insensitive comparison is needed.
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
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (PRODUCT_ID)
);
-- Note: Secondary indexes (IDX_PROD_CODE, IDX_PROD_CATEGORY) removed.
-- Snowflake does not support user-created indexes. No clustering needed for this small table.

COMMENT ON TABLE BANKING_DW.DIM_PRODUCT IS 'Banking product catalog dimension';
