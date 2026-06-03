/**********************************************************************
 * DIM_BRANCH — Branch / Location Dimension (Snowflake)
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

CREATE OR REPLACE TABLE BANKING_DW.DIM_BRANCH
(
    BRANCH_ID           INTEGER          NOT NULL,
    BRANCH_CODE         CHAR(6)          NOT NULL,
    BRANCH_NAME         VARCHAR(100)     COLLATE 'en-ci' NOT NULL,
    BRANCH_TYPE         VARCHAR(20)      COLLATE 'en-ci',
    ADDRESS_LINE_1      VARCHAR(100)     COLLATE 'en-ci',
    CITY                VARCHAR(50)      COLLATE 'en-ci',
    COUNTY              VARCHAR(50)      COLLATE 'en-ci',
    REGION              VARCHAR(50)      COLLATE 'en-ci',
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
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Branch dimension with Norwegian regional hierarchy';
