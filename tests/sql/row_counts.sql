-- ================================================================
-- Row Count Validation Queries (Category 2: R-01 to R-09)
-- ================================================================

-- R-01 to R-07: Simple row counts per table
SELECT COUNT(*) FROM {schema}.{table_name};

-- R-08: Row counts per partition (FACT_TRANSACTION by year-month)
SELECT
    EXTRACT(YEAR FROM TRANSACTION_DATE) AS TXN_YEAR,
    EXTRACT(MONTH FROM TRANSACTION_DATE) AS TXN_MONTH,
    COUNT(*) AS ROW_COUNT
FROM {schema}.FACT_TRANSACTION
GROUP BY TXN_YEAR, TXN_MONTH
ORDER BY TXN_YEAR, TXN_MONTH;

-- R-09: Distinct key counts per table
SELECT COUNT(DISTINCT {key_column}) AS DISTINCT_KEY_COUNT
FROM {schema}.{table_name};
