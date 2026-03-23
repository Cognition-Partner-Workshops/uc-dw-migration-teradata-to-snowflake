/**********************************************************************
 * DIM_BRANCH — Branch / Location Dimension (Snowflake)
 * Converted from Teradata SET table
 * Changes:
 *   - Removed SET, NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO
 *   - Removed COMPRESS clauses
 *   - Removed NOT CASESPECIFIC
 *   - Removed FORMAT on DATE columns
 *   - Replaced BYTEINT with SMALLINT
 *   - Replaced UNIQUE PRIMARY INDEX with PRIMARY KEY constraint
 *   - Removed secondary indexes
 *   - Removed COLLECT STATISTICS
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
    ETL_INSERT_TS       TIMESTAMP_NTZ    DEFAULT CURRENT_TIMESTAMP(),

    CONSTRAINT PK_DIM_BRANCH PRIMARY KEY (BRANCH_ID)
)
COMMENT = 'Branch dimension with Norwegian regional hierarchy';
