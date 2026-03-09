/**********************************************************************
 * DIM_BRANCH -- Branch / Location Dimension (Snowflake)
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

CREATE TABLE BANKING_DW.DIM_BRANCH
(
    BRANCH_ID           INTEGER          NOT NULL,
    BRANCH_CODE         CHAR(6)          NOT NULL,
    -- Note: Snowflake is case-sensitive by default. Use COLLATE 'en-ci' or UPPER()/LOWER() where case-insensitive comparison is needed.
    BRANCH_NAME         VARCHAR(100)     NOT NULL,
    BRANCH_TYPE         VARCHAR(20),
    ADDRESS_LINE_1      VARCHAR(100),
    CITY                VARCHAR(50),
    COUNTY              VARCHAR(50),
    REGION              VARCHAR(50),
    POSTAL_CODE         VARCHAR(10),
    COUNTRY_CODE        CHAR(3)          DEFAULT 'NOR',
    LATITUDE            DECIMAL(10,7),
    LONGITUDE           DECIMAL(10,7),
    MANAGER_ID          INTEGER,
    OPENING_DATE        DATE,
    CLOSING_DATE        DATE,
    IS_ACTIVE           SMALLINT         DEFAULT 1,
    EMPLOYEE_COUNT      SMALLINT,
    ETL_BATCH_ID        BIGINT,
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (BRANCH_ID)
);
-- Note: Secondary indexes (IDX_BRANCH_CODE, IDX_BRANCH_REGION) removed.
-- Snowflake does not support user-created indexes. No clustering needed for this small table.

COMMENT ON TABLE BANKING_DW.DIM_BRANCH IS 'Branch dimension with Norwegian regional hierarchy';
