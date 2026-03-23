/**********************************************************************
 * SP_AML_SCREENING (Snowflake)
 * Anti-Money Laundering screening — converted from Teradata MACRO
 * Teradata macros have no Snowflake equivalent; converted to stored procedure
 * returning result sets via RESULT_SCAN / TABLE functions.
 *
 * Changes:
 *   - Replaced REPLACE MACRO with CREATE OR REPLACE PROCEDURE
 *   - Converted macro parameters to procedure parameters
 *   - Replaced SEL with SELECT
 *   - Removed FORMAT display specifications (use TO_CHAR in client)
 *   - Replaced :parameter with :P_PARAMETER (Snowflake scripting)
 *   - Multi-statement macros split into separate result-set queries
 *     stored in a temporary table for unified output
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_AML_SCREENING(
    P_SCREENING_DATE    DATE      DEFAULT CURRENT_DATE(),
    P_LOOKBACK_DAYS     INTEGER   DEFAULT 30,
    P_AMOUNT_THRESHOLD  DECIMAL(15,2) DEFAULT 50000.00
)
RETURNS TABLE (
    PATTERN_TYPE     VARCHAR,
    CUSTOMER_ID      INTEGER,
    CUSTOMER_NAME    VARCHAR,
    KYC_STATUS       VARCHAR,
    ACCOUNT_ID       VARCHAR,
    DETAIL_1         VARCHAR,
    DETAIL_2         VARCHAR,
    DETAIL_3         VARCHAR,
    DETAIL_4         VARCHAR,
    DETAIL_5         VARCHAR
)
LANGUAGE SQL
AS
$$
DECLARE
    res RESULTSET;
BEGIN
    -- Combine all three AML patterns into a single result set
    res := (
        -- Pattern 1: Structuring — multiple transactions just below threshold
        SELECT
            'STRUCTURING' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            c.KYC_STATUS,
            a.ACCOUNT_ID,
            COUNT(*)::VARCHAR AS DETAIL_1,                          -- TXN_COUNT
            SUM(ft.BASE_CURRENCY_AMOUNT)::VARCHAR AS DETAIL_2,     -- TOTAL_AMOUNT
            AVG(ft.BASE_CURRENCY_AMOUNT)::VARCHAR AS DETAIL_3,     -- AVG_AMOUNT
            TO_CHAR(MAX(ft.TRANSACTION_DATE), 'YYYY-MM-DD') AS DETAIL_4,  -- LAST_TXN_DATE
            NULL AS DETAIL_5
        FROM BANKING_DW.FACT_TRANSACTION ft
        INNER JOIN BANKING_DW.DIM_ACCOUNT a
            ON ft.ACCOUNT_KEY = a.ACCOUNT_KEY AND a.CURRENT_FLAG = 'Y'
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
        WHERE ft.TRANSACTION_DATE BETWEEN DATEADD('day', -:P_LOOKBACK_DAYS, :P_SCREENING_DATE)
                                       AND :P_SCREENING_DATE
          AND ft.TRANSACTION_TYPE IN ('CREDIT', 'DEBIT')
          AND ft.BASE_CURRENCY_AMOUNT BETWEEN (:P_AMOUNT_THRESHOLD * 0.8) AND :P_AMOUNT_THRESHOLD
        GROUP BY c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME, c.KYC_STATUS, a.ACCOUNT_ID
        HAVING COUNT(*) >= 3

        UNION ALL

        -- Pattern 2: Rapid movement — large deposits followed by immediate withdrawals
        SELECT
            'RAPID_MOVEMENT' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            NULL AS KYC_STATUS,
            a.ACCOUNT_ID,
            TO_CHAR(cr.CREDIT_DATE, 'YYYY-MM-DD') AS DETAIL_1,          -- CREDIT_DATE
            cr.CREDIT_AMOUNT::VARCHAR AS DETAIL_2,                       -- CREDIT_AMOUNT
            TO_CHAR(dr.DEBIT_DATE, 'YYYY-MM-DD') AS DETAIL_3,           -- DEBIT_DATE
            dr.DEBIT_AMOUNT::VARCHAR AS DETAIL_4,                        -- DEBIT_AMOUNT
            DATEDIFF('day', cr.CREDIT_DATE, dr.DEBIT_DATE)::VARCHAR AS DETAIL_5  -- DAYS_BETWEEN
        FROM BANKING_DW.DIM_CUSTOMER c
        INNER JOIN BANKING_DW.DIM_ACCOUNT a
            ON c.CUSTOMER_ID = a.CUSTOMER_ID AND a.CURRENT_FLAG = 'Y'
        INNER JOIN (
            SELECT ACCOUNT_KEY, TRANSACTION_DATE AS CREDIT_DATE,
                   BASE_CURRENCY_AMOUNT AS CREDIT_AMOUNT
            FROM BANKING_DW.FACT_TRANSACTION
            WHERE TRANSACTION_TYPE = 'CREDIT'
              AND BASE_CURRENCY_AMOUNT >= :P_AMOUNT_THRESHOLD
              AND TRANSACTION_DATE BETWEEN DATEADD('day', -:P_LOOKBACK_DAYS, :P_SCREENING_DATE)
                                        AND :P_SCREENING_DATE
        ) cr ON a.ACCOUNT_KEY = cr.ACCOUNT_KEY
        INNER JOIN (
            SELECT ACCOUNT_KEY, TRANSACTION_DATE AS DEBIT_DATE,
                   BASE_CURRENCY_AMOUNT AS DEBIT_AMOUNT
            FROM BANKING_DW.FACT_TRANSACTION
            WHERE TRANSACTION_TYPE IN ('DEBIT', 'TRANSFER')
              AND BASE_CURRENCY_AMOUNT >= :P_AMOUNT_THRESHOLD * 0.9
              AND TRANSACTION_DATE BETWEEN DATEADD('day', -:P_LOOKBACK_DAYS, :P_SCREENING_DATE)
                                        AND :P_SCREENING_DATE
        ) dr ON cr.ACCOUNT_KEY = dr.ACCOUNT_KEY
            AND dr.DEBIT_DATE BETWEEN cr.CREDIT_DATE AND DATEADD('day', 3, cr.CREDIT_DATE)
        WHERE c.CURRENT_FLAG = 'Y'

        UNION ALL

        -- Pattern 3: International high-value from newly onboarded customers
        SELECT
            'NEW_CUSTOMER_INTL' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            c.KYC_STATUS,
            NULL AS ACCOUNT_ID,
            TO_CHAR(c.ONBOARDING_DATE, 'YYYY-MM-DD') AS DETAIL_1,
            DATEDIFF('day', c.ONBOARDING_DATE, :P_SCREENING_DATE)::VARCHAR AS DETAIL_2,
            COUNT(*)::VARCHAR AS DETAIL_3,                                   -- INTL_TXN_COUNT
            SUM(ft.BASE_CURRENCY_AMOUNT)::VARCHAR AS DETAIL_4,              -- TOTAL_INTL_AMOUNT
            NULL AS DETAIL_5
        FROM BANKING_DW.FACT_TRANSACTION ft
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
        WHERE ft.IS_INTERNATIONAL = 1
          AND ft.TRANSACTION_DATE BETWEEN DATEADD('day', -:P_LOOKBACK_DAYS, :P_SCREENING_DATE)
                                       AND :P_SCREENING_DATE
          AND c.ONBOARDING_DATE >= DATEADD('day', -90, :P_SCREENING_DATE)
        GROUP BY c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME,
                 c.ONBOARDING_DATE, c.KYC_STATUS
        HAVING SUM(ft.BASE_CURRENCY_AMOUNT) >= :P_AMOUNT_THRESHOLD

        ORDER BY PATTERN_TYPE, CUSTOMER_ID
    );

    RETURN TABLE(res);
END;
$$;
