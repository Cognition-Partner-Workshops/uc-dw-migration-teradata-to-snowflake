/**********************************************************************
 * DIM_BRANCH -- Branch / Location Dimension (Snowflake)
 *
 * Source: Teradata SET table with geographic hierarchy,
 *         COMPRESS, CASESPECIFIC, FORMAT.
 *
 * Conversion notes:
 *   - SET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - NOT CASESPECIFIC removed.
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - BYTEINT converted to SMALLINT.
 *   - SMALLINT COMPRESS 0 simplified to SMALLINT.
 *   - UNIQUE PRIMARY INDEX converted to PRIMARY KEY.
 *   - Secondary indexes documented as comments.
 *   - No partitioning in source; no CLUSTER BY needed (small table).
 *   - COLLECT STATISTICS removed.
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

    CONSTRAINT PK_DIM_BRANCH PRIMARY KEY (BRANCH_ID)
)
;

-- Original Teradata secondary indexes (not supported in Snowflake):
--   INDEX IDX_BRANCH_CODE    (BRANCH_CODE)
--   INDEX IDX_BRANCH_REGION  (REGION)

COMMENT ON TABLE BANKING_DW.DIM_BRANCH IS 'Branch dimension with Norwegian regional hierarchy';
