/**********************************************************************
 * Validation Checksum Queries (Snowflake)
 * Run these on Snowflake (target) and compare results with Teradata (source)
 * to verify data integrity after migration
 *
 * Conversion notes:
 * - Replaced: SEL -> SELECT
 * - Replaced: HASHROW() -> HASH()
 * - Removed: FORMAT from expressions
 * - Removed: (DECIMAL(18,2)) Teradata-style casts -> CAST(... AS DECIMAL(18,2))
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
-- Note: HASH() values will differ between Teradata and Snowflake.
-- Compare aggregates (counts, dates, active count), not individual hashes.
-- ================================================================
SELECT
    COUNT(*) AS ROW_COUNT,
    COUNT(DISTINCT CUSTOMER_ID) AS DISTINCT_CUSTOMERS,
    SUM(HASH(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT)) AS HASH_SUM,
    MIN(ONBOARDING_DATE) AS MIN_ONBOARD_DATE,
    MAX(ONBOARDING_DATE) AS MAX_ONBOARD_DATE,
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
    CAST(SUM(TRANSACTION_AMOUNT) AS DECIMAL(18,2)) AS TOTAL_AMOUNT,
    CAST(SUM(BASE_CURRENCY_AMOUNT) AS DECIMAL(18,2)) AS TOTAL_BASE_AMOUNT,
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
    CAST(SUM(snap.CLOSING_BALANCE) AS DECIMAL(18,2)) AS TOTAL_DEPOSITS,
    CAST(SUM(snap.TOTAL_DEBITS) AS DECIMAL(18,2)) AS TOTAL_DEBITS,
    CAST(SUM(snap.TOTAL_CREDITS) AS DECIMAL(18,2)) AS TOTAL_CREDITS,
    CAST(SUM(snap.INTEREST_EARNED) AS DECIMAL(18,2)) AS TOTAL_INTEREST,
    CAST(SUM(snap.FEES_CHARGED) AS DECIMAL(18,2)) AS TOTAL_FEES,
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
