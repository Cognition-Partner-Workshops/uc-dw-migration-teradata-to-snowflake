/**********************************************************************
 * VW_CUSTOMER_360 — Customer 360 View (Snowflake)
 *
 * Converted from Teradata view.
 * - REPLACE VIEW → CREATE OR REPLACE VIEW
 * - LOCKING ROW FOR ACCESS → removed (Snowflake uses MVCC)
 * - SEL → SELECT
 * - ZEROIFNULL → ZEROIFNULL (natively supported in Snowflake)
 * - FORMAT 'ZZZ,ZZZ,ZZ9.99' → removed (display formatting at client level)
 * - Correlated subquery with QUALIFY ROW_NUMBER() → ORDER BY ... LIMIT 1
 * - Date arithmetic (CURRENT_DATE - date) → DATEDIFF
 * - GROUP BY 1 → GROUP BY 1 (supported in Snowflake)
 **********************************************************************/

CREATE OR REPLACE VIEW BANKING_DW.VW_CUSTOMER_360
    COMMENT = 'Customer 360 view combining demographics, accounts, and recent transaction activity'
AS
SELECT
    c.CUSTOMER_ID,
    c.FIRST_NAME || ' ' || c.LAST_NAME AS FULL_NAME,
    c.CUSTOMER_SEGMENT,
    c.RISK_SCORE,
    c.CREDIT_RATING,
    c.KYC_STATUS,
    c.ONBOARDING_DATE,
    CAST(DATEDIFF(DAY, c.ONBOARDING_DATE, CURRENT_DATE) / 365.25 AS DECIMAL(5,1)) AS TENURE_YEARS,
    ZEROIFNULL(acct_summary.TOTAL_ACCOUNTS) AS TOTAL_ACCOUNTS,
    ZEROIFNULL(acct_summary.ACTIVE_ACCOUNTS) AS ACTIVE_ACCOUNTS,
    ZEROIFNULL(acct_summary.TOTAL_BALANCE) AS TOTAL_BALANCE,
    ZEROIFNULL(txn_summary.TXN_COUNT_90D) AS TXN_COUNT_LAST_90_DAYS,
    ZEROIFNULL(txn_summary.TXN_AMOUNT_90D) AS TXN_AMOUNT_LAST_90_DAYS,
    txn_summary.LAST_TXN_DATE,
    txn_summary.PRIMARY_CHANNEL,
    c.CITY,
    c.COUNTRY_CODE
FROM BANKING_DW.DIM_CUSTOMER c
LEFT JOIN (
    SELECT
        a.CUSTOMER_ID,
        COUNT(*) AS TOTAL_ACCOUNTS,
        SUM(CASE WHEN a.ACCOUNT_STATUS = 'ACTIVE' THEN 1 ELSE 0 END) AS ACTIVE_ACCOUNTS,
        SUM(CASE WHEN a.CURRENT_FLAG = 'Y' THEN
            COALESCE(
                (SELECT snap.CLOSING_BALANCE
                 FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
                 WHERE snap.ACCOUNT_KEY = a.ACCOUNT_KEY
                 ORDER BY snap.SNAPSHOT_DATE DESC
                 LIMIT 1),
                0)
            ELSE 0 END) AS TOTAL_BALANCE
    FROM BANKING_DW.DIM_ACCOUNT a
    WHERE a.CURRENT_FLAG = 'Y'
    GROUP BY 1
) acct_summary
    ON c.CUSTOMER_ID = acct_summary.CUSTOMER_ID
LEFT JOIN (
    SELECT
        ft.CUSTOMER_KEY,
        COUNT(*) AS TXN_COUNT_90D,
        SUM(ABS(ft.TRANSACTION_AMOUNT)) AS TXN_AMOUNT_90D,
        MAX(ft.TRANSACTION_DATE) AS LAST_TXN_DATE,
        MAX(ft.CHANNEL) AS PRIMARY_CHANNEL
    FROM BANKING_DW.FACT_TRANSACTION ft
    WHERE ft.TRANSACTION_DATE >= DATEADD(DAY, -90, CURRENT_DATE)
    GROUP BY 1
) txn_summary
    ON c.CUSTOMER_KEY = txn_summary.CUSTOMER_KEY
WHERE c.CURRENT_FLAG = 'Y'
  AND c.IS_ACTIVE = 1;
