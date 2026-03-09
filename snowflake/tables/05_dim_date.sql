/**********************************************************************
 * DIM_DATE -- Date Dimension (Snowflake)
 *
 * Source: Teradata SET table, pre-populated calendar table with
 *         Norwegian business day flags, COMPRESS, FORMAT.
 *
 * Conversion notes:
 *   - SET table / physical attributes removed.
 *   - COMPRESS clauses removed (Snowflake auto-compression).
 *   - FORMAT 'YYYY-MM-DD' removed (native DATE).
 *   - BYTEINT converted to SMALLINT.
 *   - UNIQUE PRIMARY INDEX converted to PRIMARY KEY.
 *   - Secondary indexes documented as comments.
 *   - No CLUSTER BY needed (small reference table, ~11K rows).
 *   - COLLECT STATISTICS removed.
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

    CONSTRAINT PK_DIM_DATE PRIMARY KEY (DATE_KEY)
)
;

-- Original Teradata secondary indexes (not supported in Snowflake):
--   INDEX IDX_CALENDAR_DATE  (CALENDAR_DATE)
--   INDEX IDX_YEAR_MONTH     (CALENDAR_YEAR, MONTH_NUM)

COMMENT ON TABLE BANKING_DW.DIM_DATE IS 'Calendar dimension with Norwegian holidays and fiscal year alignment';
