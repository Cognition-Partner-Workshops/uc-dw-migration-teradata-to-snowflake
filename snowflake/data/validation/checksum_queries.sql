/**********************************************************************
 * Validation Checksum Queries (Snowflake)
 *
 * Converted from Teradata validation queries.
 * Run on Snowflake (target) and compare results with Teradata (source).
 *
 * Changes:
 *   - SEL -> SELECT
 *   - HASHROW() -> HASH()
 *   - (FORMAT '...') inline formatting -> TO_CHAR()
 *   - (DECIMAL(18,2)) type casting -> ::DECIMAL(18,2)
 **********************************************************************/

-- ================================================================
-- 1. Row count validation per table
-- ================================================================
SELECT 'DIM_CUSTOMER' AS TABLE_NAME, COUNT(*) AS ROW_COUNT
FROM BANKING_DW.DIM_CUSTOMER
UNION ALL
SELECT 'DIM_ACCOUNT', COUNT(*)
FROM BANKING_DW.DIM_ACCOUNT
UNION ALL
SELECT 'DIM_PRODUCT', COUNT(*)
FROM BANKING_DW.DIM_PRODUCT
UNION ALL
SELECT 'DIM_BRANCH', COUNT(*)
FROM BANKING_DW.DIM_BRANCH
UNION ALL
SELECT 'DIM_DATE', COUNT(*)
FROM BANKING_DW.DIM_DATE
UNION ALL
SELECT 'FACT_TRANSACTION', COUNT(*)
FROM BANKING_DW.FACT_TRANSACTION
UNION ALL
SELECT 'FACT_MONTHLY_SNAPSHOT', COUNT(*)
FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT
ORDER BY 1;

-- ================================================================
-- 2. Column-level checksum: DIM_CUSTOMER
-- ================================================================
SELECT
    COUNT(*) AS ROW_COUNT,
    COUNT(DISTINCT CUSTOMER_ID) AS DISTINCT_CUSTOMERS,
    SUM(HASH(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT)) AS HASH_SUM,
    TO_CHAR(MIN(ONBOARDING_DATE), 'YYYY-MM-DD') AS MIN_ONBOARD_DATE,
    TO_CHAR(MAX(ONBOARDING_DATE), 'YYYY-MM-DD') AS MAX_ONBOARD_DATE,
    SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END) AS ACTIVE_COUNT
FROM BANKING_DW.DIM_CUSTOMER
WHERE CURRENT_FLAG = 'Y';

-- ================================================================
-- 3. Aggregate checksum: FACT_TRANSACTION
-- ================================================================
SELECT
    EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR,
    EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH,
    COUNT(*) AS TXN_COUNT,
    SUM(TRANSACTION_AMOUNT)::DECIMAL(18,2) AS TOTAL_AMOUNT,
    SUM(BASE_CURRENCY_AMOUNT)::DECIMAL(18,2) AS TOTAL_BASE_AMOUNT,
    COUNT(DISTINCT ACCOUNT_KEY) AS DISTINCT_ACCOUNTS,
    COUNT(DISTINCT CUSTOMER_KEY) AS DISTINCT_CUSTOMERS,
    SUM(CASE WHEN TRANSACTION_TYPE = 'DEBIT' THEN 1 ELSE 0 END) AS DEBIT_COUNT,
    SUM(CASE WHEN TRANSACTION_TYPE = 'CREDIT' THEN 1 ELSE 0 END) AS CREDIT_COUNT,
    SUM(CASE WHEN IS_INTERNATIONAL = 1 THEN 1 ELSE 0 END) AS INTL_COUNT
FROM BANKING_DW.FACT_TRANSACTION
GROUP BY 1, 2
ORDER BY 1, 2;

-- ================================================================
-- 4. Business-level reconciliation: Monthly balances
-- ================================================================
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

-- ================================================================
-- 5. Cross-table referential integrity checks
-- ================================================================
-- Orphaned transactions (account key not in dimension)
SELECT 'ORPHAN_TXN_ACCOUNT' AS CHECK_NAME,
     COUNT(*) AS ORPHAN_COUNT
FROM BANKING_DW.FACT_TRANSACTION ft
WHERE ft.ACCOUNT_KEY NOT IN (
    SELECT ACCOUNT_KEY FROM BANKING_DW.DIM_ACCOUNT
)
UNION ALL
-- Orphaned transactions (customer key not in dimension)
SELECT 'ORPHAN_TXN_CUSTOMER',
     COUNT(*)
FROM BANKING_DW.FACT_TRANSACTION ft
WHERE ft.CUSTOMER_KEY NOT IN (
    SELECT CUSTOMER_KEY FROM BANKING_DW.DIM_CUSTOMER
)
UNION ALL
-- Orphaned snapshots (account key not in dimension)
SELECT 'ORPHAN_SNAP_ACCOUNT',
     COUNT(*)
FROM BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
WHERE snap.ACCOUNT_KEY NOT IN (
    SELECT ACCOUNT_KEY FROM BANKING_DW.DIM_ACCOUNT
);
