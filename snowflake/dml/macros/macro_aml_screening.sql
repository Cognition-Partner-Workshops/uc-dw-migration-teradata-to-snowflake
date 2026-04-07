/**********************************************************************
 * AML_SCREENING (Snowflake)
 *
 * Anti-Money Laundering screening - converted from Teradata MACRO
 * to Snowflake stored procedure.
 *
 * Changes:
 *   - REPLACE MACRO -> CREATE OR REPLACE PROCEDURE
 *   - Macro parameters :param -> procedure parameters
 *   - DEFAULT DATE -> DEFAULT CURRENT_DATE
 *   - SEL -> SELECT
 *   - (FORMAT '...') inline formatting -> removed
 *   - Multiple result sets -> UNION ALL with PATTERN_TYPE discriminator
 *   - Date arithmetic (:screening_date - :lookback_days) ->
 *     DATEADD('day', -P_LOOKBACK_DAYS, P_SCREENING_DATE)
 *   - (date - date) -> DATEDIFF('day', ...)
 *
 * NOTE: Teradata macros return multiple result sets. Converted to a
 * single combined result set with PATTERN_TYPE column as discriminator.
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.AML_SCREENING(
    P_SCREENING_DATE DATE DEFAULT CURRENT_DATE,
    P_LOOKBACK_DAYS INTEGER DEFAULT 30,
    P_AMOUNT_THRESHOLD DECIMAL(15,2) DEFAULT 50000.00
)
RETURNS TABLE (
    PATTERN_TYPE VARCHAR(30),
    CUSTOMER_ID INTEGER,
    CUSTOMER_NAME VARCHAR(101),
    DETAIL_1 VARCHAR(100),
    DETAIL_2 VARCHAR(100),
    METRIC_1 NUMBER(18,2),
    METRIC_2 NUMBER(18,2),
    METRIC_3 NUMBER(18,2),
    COUNT_VALUE INTEGER,
    EXTRA_DATE_1 DATE,
    EXTRA_DATE_2 DATE,
    DAYS_METRIC INTEGER
)
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    v_lookback_start DATE;
    res RESULTSET;
BEGIN
    v_lookback_start := DATEADD('day', -:P_LOOKBACK_DAYS, :P_SCREENING_DATE);

    res := (
        -- Pattern 1: Structuring - multiple transactions just below threshold
        SELECT
            'STRUCTURING' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            c.KYC_STATUS AS DETAIL_1,
            a.ACCOUNT_ID AS DETAIL_2,
            SUM(ft.BASE_CURRENCY_AMOUNT) AS METRIC_1,
            AVG(ft.BASE_CURRENCY_AMOUNT) AS METRIC_2,
            NULL AS METRIC_3,
            COUNT(*) AS COUNT_VALUE,
            MAX(ft.TRANSACTION_DATE) AS EXTRA_DATE_1,
            NULL AS EXTRA_DATE_2,
            NULL AS DAYS_METRIC
        FROM BANKING_DW.FACT_TRANSACTION ft
        INNER JOIN BANKING_DW.DIM_ACCOUNT a
            ON ft.ACCOUNT_KEY = a.ACCOUNT_KEY AND a.CURRENT_FLAG = 'Y'
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
        WHERE ft.TRANSACTION_DATE BETWEEN :v_lookback_start AND :P_SCREENING_DATE
          AND ft.TRANSACTION_TYPE IN ('CREDIT', 'DEBIT')
          AND ft.BASE_CURRENCY_AMOUNT BETWEEN (:P_AMOUNT_THRESHOLD * 0.8) AND :P_AMOUNT_THRESHOLD
        GROUP BY c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME, c.KYC_STATUS, a.ACCOUNT_ID
        HAVING COUNT(*) >= 3

        UNION ALL

        -- Pattern 2: Rapid movement - large deposits followed by immediate withdrawals
        SELECT
            'RAPID_MOVEMENT' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            a.ACCOUNT_ID AS DETAIL_1,
            NULL AS DETAIL_2,
            cr.CREDIT_AMOUNT AS METRIC_1,
            dr.DEBIT_AMOUNT AS METRIC_2,
            NULL AS METRIC_3,
            NULL AS COUNT_VALUE,
            cr.CREDIT_DATE AS EXTRA_DATE_1,
            dr.DEBIT_DATE AS EXTRA_DATE_2,
            DATEDIFF('day', cr.CREDIT_DATE, dr.DEBIT_DATE) AS DAYS_METRIC
        FROM BANKING_DW.DIM_CUSTOMER c
        INNER JOIN BANKING_DW.DIM_ACCOUNT a
            ON c.CUSTOMER_ID = a.CUSTOMER_ID AND a.CURRENT_FLAG = 'Y'
        INNER JOIN (
            SELECT ACCOUNT_KEY, TRANSACTION_DATE AS CREDIT_DATE,
                   BASE_CURRENCY_AMOUNT AS CREDIT_AMOUNT
            FROM BANKING_DW.FACT_TRANSACTION
            WHERE TRANSACTION_TYPE = 'CREDIT'
              AND BASE_CURRENCY_AMOUNT >= :P_AMOUNT_THRESHOLD
              AND TRANSACTION_DATE BETWEEN :v_lookback_start AND :P_SCREENING_DATE
        ) cr ON a.ACCOUNT_KEY = cr.ACCOUNT_KEY
        INNER JOIN (
            SELECT ACCOUNT_KEY, TRANSACTION_DATE AS DEBIT_DATE,
                   BASE_CURRENCY_AMOUNT AS DEBIT_AMOUNT
            FROM BANKING_DW.FACT_TRANSACTION
            WHERE TRANSACTION_TYPE IN ('DEBIT', 'TRANSFER')
              AND BASE_CURRENCY_AMOUNT >= :P_AMOUNT_THRESHOLD * 0.9
              AND TRANSACTION_DATE BETWEEN :v_lookback_start AND :P_SCREENING_DATE
        ) dr ON cr.ACCOUNT_KEY = dr.ACCOUNT_KEY
            AND dr.DEBIT_DATE BETWEEN cr.CREDIT_DATE AND DATEADD('day', 3, cr.CREDIT_DATE)
        WHERE c.CURRENT_FLAG = 'Y'

        UNION ALL

        -- Pattern 3: International high-value transactions from newly onboarded customers
        SELECT
            'NEW_CUSTOMER_INTL' AS PATTERN_TYPE,
            c.CUSTOMER_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            c.KYC_STATUS AS DETAIL_1,
            NULL AS DETAIL_2,
            SUM(ft.BASE_CURRENCY_AMOUNT) AS METRIC_1,
            NULL AS METRIC_2,
            NULL AS METRIC_3,
            COUNT(*) AS COUNT_VALUE,
            c.ONBOARDING_DATE AS EXTRA_DATE_1,
            NULL AS EXTRA_DATE_2,
            DATEDIFF('day', c.ONBOARDING_DATE, :P_SCREENING_DATE) AS DAYS_METRIC
        FROM BANKING_DW.FACT_TRANSACTION ft
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
        WHERE ft.IS_INTERNATIONAL = 1
          AND ft.TRANSACTION_DATE BETWEEN :v_lookback_start AND :P_SCREENING_DATE
          AND c.ONBOARDING_DATE >= DATEADD('day', -90, :P_SCREENING_DATE)
        GROUP BY c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME,
                 c.ONBOARDING_DATE, c.KYC_STATUS
        HAVING SUM(ft.BASE_CURRENCY_AMOUNT) >= :P_AMOUNT_THRESHOLD

        ORDER BY PATTERN_TYPE, METRIC_1 DESC
    );
    RETURN TABLE(res);
END;
$$;
