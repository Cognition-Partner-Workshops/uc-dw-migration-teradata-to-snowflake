-- ================================================================
-- Referential Integrity Queries (Category 4: RI-01 to RI-10)
-- ================================================================

-- RI-01: No orphan transactions (ACCOUNT_KEY)
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_TRANSACTION ft
WHERE ft.ACCOUNT_KEY NOT IN (
    SELECT ACCOUNT_KEY FROM {schema}.DIM_ACCOUNT
);

-- RI-02: No orphan transactions (CUSTOMER_KEY)
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_TRANSACTION ft
WHERE ft.CUSTOMER_KEY NOT IN (
    SELECT CUSTOMER_KEY FROM {schema}.DIM_CUSTOMER
);

-- RI-03: No orphan snapshots (ACCOUNT_KEY)
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
WHERE snap.ACCOUNT_KEY NOT IN (
    SELECT ACCOUNT_KEY FROM {schema}.DIM_ACCOUNT
);

-- RI-04: No orphan accounts (CUSTOMER_ID)
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.DIM_ACCOUNT da
WHERE da.CUSTOMER_ID NOT IN (
    SELECT CUSTOMER_ID FROM {schema}.DIM_CUSTOMER
);

-- RI-05: No orphan accounts (BRANCH_ID)
-- Note: BRANCH_ID can be NULL for online/mobile accounts
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.DIM_ACCOUNT da
WHERE da.BRANCH_ID IS NOT NULL
  AND da.BRANCH_ID NOT IN (
    SELECT BRANCH_ID FROM {schema}.DIM_BRANCH
);

-- RI-06: No orphan accounts (PRODUCT_ID)
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.DIM_ACCOUNT da
WHERE da.PRODUCT_ID NOT IN (
    SELECT PRODUCT_ID FROM {schema}.DIM_PRODUCT
);

-- RI-07: FACT_TRANSACTION.DATE_KEY references DIM_DATE
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_TRANSACTION ft
WHERE ft.DATE_KEY NOT IN (
    SELECT DATE_KEY FROM {schema}.DIM_DATE
);

-- RI-08: FACT_TRANSACTION.PRODUCT_ID references DIM_PRODUCT
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_TRANSACTION ft
WHERE ft.PRODUCT_ID NOT IN (
    SELECT PRODUCT_ID FROM {schema}.DIM_PRODUCT
);

-- RI-09: Detect orphans when dimension record is missing (negative test)
-- This test should INSERT a fact row with a non-existent ACCOUNT_KEY,
-- verify orphan detection, then ROLLBACK. Implemented in Python test.

-- RI-10: Snapshot CUSTOMER_KEY references DIM_CUSTOMER
SELECT COUNT(*) AS ORPHAN_COUNT
FROM {schema}.FACT_MONTHLY_ACCOUNT_SNAPSHOT snap
WHERE snap.CUSTOMER_KEY NOT IN (
    SELECT CUSTOMER_KEY FROM {schema}.DIM_CUSTOMER
);
