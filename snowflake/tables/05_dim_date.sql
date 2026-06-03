/**********************************************************************
 * DIM_DATE — Date Dimension (Snowflake)
 *
 * Converted from Teradata SET table.
 * - SET → removed
 * - NO FALLBACK, JOURNAL, CHECKSUM, MERGEBLOCKRATIO → removed
 * - BYTEINT → SMALLINT
 * - FORMAT → removed (display formatting at session/client level)
 * - COMPRESS → removed (automatic in Snowflake)
 * - UNIQUE PRIMARY INDEX / secondary indexes → removed
 * - COLLECT STATISTICS → removed
 **********************************************************************/

CREATE OR REPLACE TABLE BANKING_DW.DIM_DATE
(
    DATE_KEY            INTEGER          NOT NULL,
    CALENDAR_DATE       DATE             NOT NULL,
    DAY_OF_WEEK         SMALLINT         NOT NULL,
    DAY_NAME            VARCHAR(10)      NOT NULL,
    DAY_OF_MONTH        SMALLINT         NOT NULL,
    DAY_OF_YEAR         SMALLINT         NOT NULL,
    WEEK_OF_YEAR        SMALLINT         NOT NULL,
    ISO_WEEK            SMALLINT         NOT NULL,
    MONTH_NUM           SMALLINT         NOT NULL,
    MONTH_NAME          VARCHAR(15)      NOT NULL,
    MONTH_SHORT         CHAR(3)          NOT NULL,
    QUARTER_NUM         SMALLINT         NOT NULL,
    QUARTER_NAME        CHAR(2)          NOT NULL,
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
    SAME_DAY_PREV_YEAR  DATE
)
COMMENT = 'Calendar dimension with Norwegian holidays and fiscal year alignment';
