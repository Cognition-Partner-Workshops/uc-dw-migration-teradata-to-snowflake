/**********************************************************************
 * Row Count Validation — Snowflake Version
 * Run on Snowflake target and compare with Teradata source counts
 * See data/validation/expected_row_counts.csv for expected values
 **********************************************************************/

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
