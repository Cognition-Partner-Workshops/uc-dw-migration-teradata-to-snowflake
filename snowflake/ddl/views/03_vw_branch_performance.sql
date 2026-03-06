/**********************************************************************
 * VW_BRANCH_PERFORMANCE -- Branch Performance Dashboard View (Snowflake)
 *
 * Converted from Teradata REPLACE VIEW.
 * Key changes:
 *   - REPLACE VIEW -> CREATE OR REPLACE VIEW
 *   - LOCKING ROW FOR ACCESS removed
 *   - SEL -> SELECT
 *   - Inline FORMAT clauses removed (use TO_CHAR in presentation layer)
 *   - TRIM(col (FORMAT '9999')) -> CAST(col AS VARCHAR)
 *   - CSUM(expr, order_col) -> SUM(expr) OVER (PARTITION BY ...
 *       ORDER BY order_col ROWS UNBOUNDED PRECEDING)
 *   - MAVG(expr, 3, order_col) -> AVG(expr) OVER (PARTITION BY ...
 *       ORDER BY order_col ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
 *   - NULLIFZERO() retained (natively supported in Snowflake)
 *   - RANK() and nested window functions retained (supported)
 **********************************************************************/

CREATE OR REPLACE VIEW BANKING_DW.VW_BRANCH_PERFORMANCE
AS
SELECT
    b.BRANCH_ID,
    b.BRANCH_NAME,
    b.BRANCH_TYPE,
    b.REGION,
    b.CITY,
    snap.SNAPSHOT_MONTH_KEY,
    d.MONTH_NAME || ' ' || CAST(d.CALENDAR_YEAR AS VARCHAR) AS MONTH_LABEL,
    COUNT(DISTINCT snap.ACCOUNT_KEY) AS ACCOUNTS_SERVICED,
    COUNT(DISTINCT snap.CUSTOMER_KEY) AS CUSTOMERS_SERVICED,
    SUM(snap.CLOSING_BALANCE) AS TOTAL_DEPOSITS,
    SUM(snap.TOTAL_DEBITS + snap.TOTAL_CREDITS) AS TOTAL_VOLUME,
    SUM(snap.FEES_CHARGED) AS TOTAL_FEES_EARNED,
    SUM(snap.INTEREST_CHARGED) AS TOTAL_INTEREST_INCOME,
    AVG(snap.CLOSING_BALANCE) AS AVG_ACCOUNT_BALANCE,
    /* CSUM -> SUM window function with ROWS UNBOUNDED PRECEDING */
    SUM(SUM(snap.FEES_CHARGED))
        OVER (PARTITION BY b.BRANCH_ID
              ORDER BY snap.SNAPSHOT_MONTH_KEY
              ROWS UNBOUNDED PRECEDING) AS CUMULATIVE_FEES_YTD,
    /* MAVG(expr, 3, order_col) -> AVG with 3-row sliding window */
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
  AND snap.SNAPSHOT_DATE >= DATEADD('month', -24, CURRENT_DATE)
GROUP BY b.BRANCH_ID, b.BRANCH_NAME, b.BRANCH_TYPE, b.REGION, b.CITY,
         snap.SNAPSHOT_MONTH_KEY, d.MONTH_NAME, d.CALENDAR_YEAR;

COMMENT ON VIEW BANKING_DW.VW_BRANCH_PERFORMANCE IS 'Monthly branch performance with cumulative sums, moving averages, and regional rankings';
