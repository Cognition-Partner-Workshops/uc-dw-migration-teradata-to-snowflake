/**********************************************************************
 * VW_BRANCH_PERFORMANCE -- Branch Performance Dashboard View (Snowflake)
 *
 * Source: Teradata REPLACE VIEW with LOCKING ROW FOR ACCESS, SEL,
 *         CSUM, MAVG, RANK(), NULLIFZERO, inline FORMAT,
 *         TRIM(col (FORMAT '9999')).
 *
 * Conversion notes:
 *   - REPLACE VIEW converted to CREATE OR REPLACE VIEW.
 *   - LOCKING ROW FOR ACCESS removed (Snowflake MVCC).
 *   - SEL converted to SELECT.
 *   - CSUM(expr, sort_col) converted to
 *       SUM(expr) OVER (PARTITION BY ... ORDER BY sort_col
 *                        ROWS UNBOUNDED PRECEDING).
 *     Note: The Teradata CSUM is applied over the GROUP BY result set.
 *     In Snowflake we use an explicit window function. The PARTITION BY
 *     on BRANCH_ID resets the cumulative sum per branch per implicit
 *     grouping context. For a true YTD calculation we also partition by
 *     the calendar year extracted from SNAPSHOT_MONTH_KEY.
 *   - MAVG(expr, 3, sort_col) converted to
 *       AVG(expr) OVER (PARTITION BY ... ORDER BY sort_col
 *                        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW).
 *   - NULLIFZERO retained (natively supported in Snowflake).
 *   - Inline FORMAT 'ZZZ,ZZZ,ZZZ,ZZ9.99' removed (presentation layer).
 *   - TRIM(col (FORMAT '9999')) converted to TRIM(TO_CHAR(col)).
 *   - ADD_MONTHS retained (natively supported in Snowflake).
 *   - RANK() OVER retained (natively supported in Snowflake).
 *   - COMMENT ON syntax retained.
 **********************************************************************/

CREATE OR REPLACE VIEW BANKING_DW.VW_BRANCH_PERFORMANCE AS
SELECT
    b.BRANCH_ID,
    b.BRANCH_NAME,
    b.BRANCH_TYPE,
    b.REGION,
    b.CITY,
    snap.SNAPSHOT_MONTH_KEY,
    d.MONTH_NAME || ' ' || TRIM(TO_CHAR(d.CALENDAR_YEAR)) AS MONTH_LABEL,
    COUNT(DISTINCT snap.ACCOUNT_KEY) AS ACCOUNTS_SERVICED,
    COUNT(DISTINCT snap.CUSTOMER_KEY) AS CUSTOMERS_SERVICED,
    SUM(snap.CLOSING_BALANCE) AS TOTAL_DEPOSITS,
    SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS) AS TOTAL_VOLUME,
    SUM(snap.FEES_CHARGED) AS TOTAL_FEES_EARNED,
    SUM(snap.INTEREST_CHARGED) AS TOTAL_INTEREST_INCOME,
    AVG(snap.CLOSING_BALANCE) AS AVG_ACCOUNT_BALANCE,
    /* Teradata CSUM -> Snowflake cumulative SUM window function */
    SUM(SUM(snap.FEES_CHARGED))
        OVER (PARTITION BY b.BRANCH_ID, FLOOR(snap.SNAPSHOT_MONTH_KEY / 100)
              ORDER BY snap.SNAPSHOT_MONTH_KEY
              ROWS UNBOUNDED PRECEDING) AS CUMULATIVE_FEES_YTD,
    /* Teradata MAVG -> Snowflake AVG window function with 3-row frame */
    AVG(SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS))
        OVER (PARTITION BY b.BRANCH_ID
              ORDER BY snap.SNAPSHOT_MONTH_KEY
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS MOVING_AVG_VOLUME_3M,
    /* Rank branches within region */
    RANK() OVER (PARTITION BY b.REGION, snap.SNAPSHOT_MONTH_KEY
                 ORDER BY SUM(snap.CLOSING_BALANCE) DESC) AS REGION_DEPOSIT_RANK,
    SUM(snap.CLOSING_BALANCE) /
        NULLIFZERO(SUM(SUM(snap.CLOSING_BALANCE))
                   OVER (PARTITION BY b.REGION, snap.SNAPSHOT_MONTH_KEY)) * 100
        AS PCT_OF_REGION_DEPOSITS
FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
INNER JOIN BANKING_DW.DIM_BRANCH b
    ON snap.BRANCH_ID = b.BRANCH_ID
INNER JOIN BANKING_DW.DIM_DATE d
    ON snap.SNAPSHOT_DATE = d.CALENDAR_DATE
WHERE b.IS_ACTIVE = 1
  AND snap.SNAPSHOT_DATE >= ADD_MONTHS(CURRENT_DATE, -24)
GROUP BY b.BRANCH_ID, b.BRANCH_NAME, b.BRANCH_TYPE, b.REGION, b.CITY,
         snap.SNAPSHOT_MONTH_KEY, d.MONTH_NAME, d.CALENDAR_YEAR;

COMMENT ON VIEW BANKING_DW.VW_BRANCH_PERFORMANCE IS 'Monthly branch performance with cumulative sums, moving averages, and regional rankings';
