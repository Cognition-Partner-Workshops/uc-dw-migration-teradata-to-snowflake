CREATE OR REPLACE FUNCTION BANKING_DW.DAILY_BALANCE_CHECK(check_date DATE)
RETURNS TABLE (
    CHECK_TYPE VARCHAR(30),
    ACCOUNT_TYPE VARCHAR(20),
    CURRENCY_CODE VARCHAR(3),
    ACCOUNT_COUNT NUMBER(38,0),
    TOTAL_BALANCE NUMBER(38,2),
    AVG_BALANCE NUMBER(38,2),
    MIN_BALANCE NUMBER(38,2),
    MAX_BALANCE NUMBER(38,2)
)
LANGUAGE SQL
COMMENT = 'AMBER: fail-closed legacy grouping defect; Q-DBC-1 requires business approval before returning data'
AS
$$
    -- No valid legacy result exists; do not silently implement latest-before-aggregate.
    SELECT
        'BALANCE_SUMMARY'::VARCHAR(30),
        NULL::VARCHAR(20),
        NULL::VARCHAR(3),
        NULL::NUMBER(38,0),
        NULL::NUMBER(38,2),
        NULL::NUMBER(38,2),
        NULL::NUMBER(38,2),
        NULL::NUMBER(38,2)
    WHERE TO_NUMBER(
        'DBC_LEGACY_GROUPING_UNRESOLVED:' || COALESCE(TO_CHAR(check_date, 'YYYY-MM-DD'), 'NULL')
    ) = 0
$$;
