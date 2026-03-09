/**********************************************************************
 * DIM_BRANCH -- Branch / Location Dimension (Snowflake)
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

CREATE OR REPLACE TABLE BANKING_DW.DIM_BRANCH
(
    BRANCH_ID           INTEGER          NOT NULL,
    BRANCH_CODE         CHAR(6)          NOT NULL,
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
    ETL_INSERT_TS       TIMESTAMP_NTZ(0) DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0),

    -- Primary key (was Teradata UNIQUE PRIMARY INDEX UPI_BRANCH_ID)
    CONSTRAINT PK_DIM_BRANCH PRIMARY KEY (BRANCH_ID)
)
COMMENT = 'Branch dimension with Norwegian regional hierarchy'
;

/*
 * Original Teradata secondary indexes (informational only):
 *   INDEX IDX_BRANCH_CODE (BRANCH_CODE)
 *   INDEX IDX_BRANCH_REGION (REGION)
 *
 * Snowflake does not support secondary indexes.
 * Consider search optimization service for frequently filtered columns.
 */
