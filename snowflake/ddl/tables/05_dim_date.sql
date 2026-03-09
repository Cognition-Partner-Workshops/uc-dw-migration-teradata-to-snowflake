/**********************************************************************
 * DIM_DATE -- Date Dimension (Snowflake)
 *
 * Pre-populated calendar table with Norwegian business day flags.
 * Converted from Teradata SET table.
 * - SET table semantics removed
 * - NO FALLBACK / JOURNAL / CHECKSUM / MERGEBLOCKRATIO removed
 * - FORMAT clause removed
 * - COMPRESS removed (automatic in Snowflake)
 * - BYTEINT  ->  SMALLINT
 * - UNIQUE PRIMARY INDEX  ->  PRIMARY KEY constraint
 * - Secondary indexes  ->  noted as comments
 * - COLLECT STATISTICS removed
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_DATE
(
    DATE_KEY            INTEGER          NOT NULL,   -- YYYYMMDD format
    CALENDAR_DATE       DATE             NOT NULL,
    DAY_OF_WEEK         SMALLINT         NOT NULL,   -- 1=Monday, 7=Sunday
    DAY_NAME            VARCHAR(10)      NOT NULL,
    DAY_OF_MONTH        SMALLINT         NOT NULL,
    DAY_OF_YEAR         SMALLINT         NOT NULL,
    WEEK_OF_YEAR        SMALLINT         NOT NULL,
    ISO_WEEK            SMALLINT         NOT NULL,
    MONTH_NUM           SMALLINT         NOT NULL,
    MONTH_NAME          VARCHAR(15)      NOT NULL,
    MONTH_SHORT         CHAR(3)          NOT NULL,
    QUARTER_NUM         SMALLINT         NOT NULL,
    QUARTER_NAME        CHAR(2)          NOT NULL,    -- Q1, Q2, Q3, Q4
    HALF_YEAR           SMALLINT         NOT NULL,
    CALENDAR_YEAR       SMALLINT         NOT NULL,
    FISCAL_YEAR         SMALLINT         NOT NULL,
    FISCAL_QUARTER      SMALLINT         NOT NULL,
    IS_WEEKEND          SMALLINT         NOT NULL,
    IS_NORWEGIAN_HOLIDAY SMALLINT        DEFAULT 0,
    HOLIDAY_NAME        VARCHAR(50),
    IS_BUSINESS_DAY     SMALLINT         NOT NULL,
    IS_MONTH_END        SMALLINT         NOT NULL,
    IS_QUARTER_END      SMALLINT         NOT NULL,
    IS_YEAR_END         SMALLINT         NOT NULL,
    PRIOR_DAY_DATE      DATE,
    NEXT_DAY_DATE       DATE,
    SAME_DAY_PREV_YEAR  DATE,

    -- Primary key (was Teradata UNIQUE PRIMARY INDEX UPI_DATE_KEY)
    CONSTRAINT PK_DIM_DATE PRIMARY KEY (DATE_KEY)
)
COMMENT = 'Calendar dimension with Norwegian holidays and fiscal year alignment'
;

/*
 * Original Teradata secondary indexes (informational only):
 *   INDEX IDX_CALENDAR_DATE (CALENDAR_DATE)
 *   INDEX IDX_YEAR_MONTH (CALENDAR_YEAR, MONTH_NUM)
 *
 * Snowflake does not support secondary indexes.
 * Consider search optimization service for frequently filtered columns.
 */
