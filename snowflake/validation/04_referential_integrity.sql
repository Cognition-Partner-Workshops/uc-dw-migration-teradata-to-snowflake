/**********************************************************************
 * Cross-Table Referential Integrity Checks — Snowflake Version
 * All counts should be zero (no orphaned records)
 **********************************************************************/

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
)

ORDER BY CHECK_NAME;
