/**********************************************************************
 * Column-Level Checksum Validation — Snowflake Version
 * Compare these results with the Teradata source checksums
 * Note: HASH() values will differ from Teradata HASHROW() — compare
 *       only the structural metrics (counts, dates, sums)
 **********************************************************************/

-- ================================================================
-- 1. DIM_CUSTOMER checksum
-- ================================================================
SELECT
    COUNT(*) AS ROW_COUNT,
    COUNT(DISTINCT CUSTOMER_ID) AS DISTINCT_CUSTOMERS,
    -- Note: HASH() output differs from Teradata HASHROW(); compare counts only
    SUM(HASH(CUSTOMER_ID, FIRST_NAME, LAST_NAME, CUSTOMER_SEGMENT)) AS HASH_SUM,
    TO_CHAR(MIN(ONBOARDING_DATE), 'YYYY-MM-DD') AS MIN_ONBOARD_DATE,
    TO_CHAR(MAX(ONBOARDING_DATE), 'YYYY-MM-DD') AS MAX_ONBOARD_DATE,
    SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END) AS ACTIVE_COUNT
FROM BANKING_DW.DIM_CUSTOMER
WHERE CURRENT_FLAG = 'Y';

-- ================================================================
-- 2. FACT_TRANSACTION aggregate checksum
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
