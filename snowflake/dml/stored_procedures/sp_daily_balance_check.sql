/**********************************************************************
 * SP_DAILY_BALANCE_CHECK -- Daily Balance Reconciliation (Snowflake)
 * Converted from Teradata MACRO BANKING_DW.DAILY_BALANCE_CHECK
 * - Replaced: REPLACE MACRO -> CREATE OR REPLACE PROCEDURE
 * - Replaced: :param -> procedure parameter references
 * - Replaced: SEL -> SELECT
 * - Removed: FORMAT expressions
 * - QUALIFY ROW_NUMBER() kept (supported in Snowflake)
 * - Multi-statement macro combined with UNION ALL
 * - Uses Snowflake SQL Scripting with RESULTSET
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_DAILY_BALANCE_CHECK(
    CHECK_DATE DATE DEFAULT CURRENT_DATE()
)
RETURNS TABLE (
    CHECK_TYPE          VARCHAR(30),
    DETAIL_1            VARCHAR(100),
    DETAIL_2            VARCHAR(100),
    DETAIL_3            VARCHAR(100),
    DETAIL_4            VARCHAR(100),
    DETAIL_5            VARCHAR(100),
    DETAIL_6            VARCHAR(100),
    DETAIL_7            VARCHAR(100)
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
            a.ACCOUNT_TYPE AS DETAIL_1,
            a.CURRENCY_CODE AS DETAIL_2,
            CAST(COUNT(*) AS VARCHAR) AS DETAIL_3,
            CAST(SUM(ft.RUNNING_BALANCE) AS VARCHAR) AS DETAIL_4,
            CAST(AVG(ft.RUNNING_BALANCE) AS VARCHAR) AS DETAIL_5,
            CAST(MIN(ft.RUNNING_BALANCE) AS VARCHAR) AS DETAIL_6,
            CAST(MAX(ft.RUNNING_BALANCE) AS VARCHAR) AS DETAIL_7
        FROM BANKING_DW.DIM_ACCOUNT a
        INNER JOIN BANKING_DW.FACT_TRANSACTION ft
            ON a.ACCOUNT_KEY = ft.ACCOUNT_KEY
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_STATUS = 'ACTIVE'
          AND ft.TRANSACTION_DATE = :CHECK_DATE
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ft.ACCOUNT_KEY
                                   ORDER BY ft.TRANSACTION_TS DESC) = 1
        GROUP BY a.ACCOUNT_TYPE, a.CURRENCY_CODE

        UNION ALL

        -- Accounts with negative balances (excluding credit products)
        SELECT
            'NEGATIVE_BALANCE_ALERT' AS CHECK_TYPE,
            a.ACCOUNT_ID AS DETAIL_1,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS DETAIL_2,
            a.ACCOUNT_TYPE AS DETAIL_3,
            CAST(ft.RUNNING_BALANCE AS VARCHAR) AS DETAIL_4,
            CAST(a.OVERDRAFT_LIMIT AS VARCHAR) AS DETAIL_5,
            CAST(ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT AS VARCHAR) AS DETAIL_6,
            NULL AS DETAIL_7
        FROM BANKING_DW.DIM_ACCOUNT a
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON a.CUSTOMER_ID = c.CUSTOMER_ID AND c.CURRENT_FLAG = 'Y'
        INNER JOIN BANKING_DW.FACT_TRANSACTION ft
            ON a.ACCOUNT_KEY = ft.ACCOUNT_KEY
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_TYPE NOT IN ('CREDIT_CARD', 'LOAN')
          AND ft.TRANSACTION_DATE = :CHECK_DATE
          AND ft.RUNNING_BALANCE < 0
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ft.ACCOUNT_KEY
                                   ORDER BY ft.TRANSACTION_TS DESC) = 1

        ORDER BY CHECK_TYPE, DETAIL_1
    );
    RETURN TABLE(res);
END;
$$;
