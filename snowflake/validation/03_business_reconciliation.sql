/**********************************************************************
 * Business-Level Reconciliation — Snowflake Version
 * Monthly balance totals must match Teradata source exactly
 **********************************************************************/

SELECT
    snap.SNAPSHOT_MONTH_KEY,
    SUM(snap.CLOSING_BALANCE)::DECIMAL(18,2) AS TOTAL_DEPOSITS,
    SUM(snap.TOTAL_DEBITS)::DECIMAL(18,2) AS TOTAL_DEBITS,
    SUM(snap.TOTAL_CREDITS)::DECIMAL(18,2) AS TOTAL_CREDITS,
    SUM(snap.INTEREST_EARNED)::DECIMAL(18,2) AS TOTAL_INTEREST,
    SUM(snap.FEES_CHARGED)::DECIMAL(18,2) AS TOTAL_FEES,
    COUNT(*) AS ACCOUNT_COUNT
FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
GROUP BY 1
ORDER BY 1;
