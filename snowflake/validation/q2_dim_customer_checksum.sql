-- Port of check 2 in data/validation/checksum_queries.sql (DIM_CUSTOMER column checksum).
-- Waiver W1-hashrow: SUM(HASHROW(...)) has no cross-engine equivalent. HASH_SUM is the
-- sum over rows of the first 16 hex digits (64 bits, unsigned) of SHA-256 over the UTF-8
-- canonical string CUSTOMER_ID | FIRST_NAME | LAST_NAME | CUSTOMER_SEGMENT, joined by
-- CHR(31), NULL rendered as \N, values case- and whitespace-preserving. COLLATE '' drops
-- the en-ci collation so the hashed bytes are exactly the stored values.
-- (FORMAT 'YYYY-MM-DD') is display-only in Teradata: MIN/MAX stay DATE values.
SELECT
    COUNT(*) AS ROW_COUNT,
    COUNT(DISTINCT CUSTOMER_ID) AS DISTINCT_CUSTOMERS,
    SUM(TO_NUMBER(SUBSTR(SHA2(
        COALESCE(TO_VARCHAR(CUSTOMER_ID), '\\N') || CHR(31) ||
        COALESCE(COLLATE(FIRST_NAME, ''), '\\N') || CHR(31) ||
        COALESCE(COLLATE(LAST_NAME, ''), '\\N') || CHR(31) ||
        COALESCE(COLLATE(CUSTOMER_SEGMENT, ''), '\\N'),
        256), 1, 16), 'XXXXXXXXXXXXXXXX')) AS HASH_SUM,
    MIN(ONBOARDING_DATE) AS MIN_ONBOARD_DATE,
    MAX(ONBOARDING_DATE) AS MAX_ONBOARD_DATE,
    SUM(CASE WHEN IS_ACTIVE = 1 THEN 1 ELSE 0 END) AS ACTIVE_COUNT
FROM BANKING_DW.BANKING_DW.DIM_CUSTOMER
WHERE CURRENT_FLAG = 'Y'
