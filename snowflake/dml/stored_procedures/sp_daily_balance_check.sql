/**********************************************************************
 * SP_DAILY_BALANCE_CHECK (Snowflake)
 * Daily balance reconciliation — converted from Teradata MACRO
 * Teradata macros have no Snowflake equivalent; converted to stored procedure
 *
 * Changes:
 *   - Replaced REPLACE MACRO with CREATE OR REPLACE PROCEDURE
 *   - Replaced SEL with SELECT
 *   - Removed FORMAT display specifications
 *   - Replaced :parameter with :P_PARAMETER
 *   - QUALIFY ROW_NUMBER() kept (natively supported)
 *   - Multi-statement macro combined into single UNION ALL query
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_DAILY_BALANCE_CHECK(
    P_CHECK_DATE DATE
)
RETURNS TABLE (
    CHECK_TYPE       VARCHAR,
    ACCOUNT_ID       VARCHAR,
    CUSTOMER_NAME    VARCHAR,
    ACCOUNT_TYPE     VARCHAR,
    CURRENCY_CODE    VARCHAR,
    ACCOUNT_COUNT    INTEGER,
    TOTAL_BALANCE    DECIMAL(15,2),
    AVG_BALANCE      DECIMAL(15,2),
    MIN_BALANCE      DECIMAL(15,2),
    MAX_BALANCE      DECIMAL(15,2),
    OVERDRAFT_LIMIT  DECIMAL(15,2),
    OVER_LIMIT_AMOUNT DECIMAL(15,2)
)
LANGUAGE SQL
AS
$$
DECLARE
    res RESULTSET;
BEGIN
    res := (
        -- Summary of all account balances as of the check date
        SELECT
            'BALANCE_SUMMARY' AS CHECK_TYPE,
            NULL AS ACCOUNT_ID,
            NULL AS CUSTOMER_NAME,
            a.ACCOUNT_TYPE,
            a.CURRENCY_CODE,
            COUNT(*) AS ACCOUNT_COUNT,
            SUM(ft.RUNNING_BALANCE) AS TOTAL_BALANCE,
            AVG(ft.RUNNING_BALANCE) AS AVG_BALANCE,
            MIN(ft.RUNNING_BALANCE) AS MIN_BALANCE,
            MAX(ft.RUNNING_BALANCE) AS MAX_BALANCE,
            NULL AS OVERDRAFT_LIMIT,
            NULL AS OVER_LIMIT_AMOUNT
        FROM BANKING_DW.DIM_ACCOUNT a
        INNER JOIN BANKING_DW.FACT_TRANSACTION ft
            ON a.ACCOUNT_KEY = ft.ACCOUNT_KEY
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_STATUS = 'ACTIVE'
          AND ft.TRANSACTION_DATE = :P_CHECK_DATE
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ft.ACCOUNT_KEY
                                   ORDER BY ft.TRANSACTION_TS DESC) = 1
        GROUP BY a.ACCOUNT_TYPE, a.CURRENCY_CODE

        UNION ALL

        -- Accounts with negative balances (excluding credit products)
        SELECT
            'NEGATIVE_BALANCE_ALERT' AS CHECK_TYPE,
            a.ACCOUNT_ID,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS CUSTOMER_NAME,
            a.ACCOUNT_TYPE,
            NULL AS CURRENCY_CODE,
            NULL AS ACCOUNT_COUNT,
            ft.RUNNING_BALANCE AS TOTAL_BALANCE,
            NULL AS AVG_BALANCE,
            NULL AS MIN_BALANCE,
            NULL AS MAX_BALANCE,
            a.OVERDRAFT_LIMIT,
            ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT AS OVER_LIMIT_AMOUNT
        FROM BANKING_DW.DIM_ACCOUNT a
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON a.CUSTOMER_ID = c.CUSTOMER_ID AND c.CURRENT_FLAG = 'Y'
        INNER JOIN BANKING_DW.FACT_TRANSACTION ft
            ON a.ACCOUNT_KEY = ft.ACCOUNT_KEY
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_TYPE NOT IN ('CREDIT_CARD', 'LOAN')
          AND ft.TRANSACTION_DATE = :P_CHECK_DATE
          AND ft.RUNNING_BALANCE < 0
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ft.ACCOUNT_KEY
                                   ORDER BY ft.TRANSACTION_TS DESC) = 1

        ORDER BY CHECK_TYPE, ACCOUNT_TYPE
    );

    RETURN TABLE(res);
END;
$$;
