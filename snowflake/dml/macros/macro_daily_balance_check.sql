/**********************************************************************
 * DAILY_BALANCE_CHECK (Snowflake)
 *
 * Converted from Teradata MACRO to Snowflake stored procedure.
 * Teradata macros have no direct Snowflake equivalent; stored procedures
 * with EXECUTE IMMEDIATE or result sets are the closest match.
 *
 * Changes:
 *   - REPLACE MACRO -> CREATE OR REPLACE PROCEDURE
 *   - Macro parameter :check_date -> procedure parameter
 *   - SEL -> SELECT
 *   - (FORMAT '...') inline formatting -> removed (use reporting layer)
 *   - QUALIFY ROW_NUMBER() -> QUALIFY (natively supported)
 *   - Multiple result sets in macro -> two separate result-set procedures
 *     (Snowflake procedures return a single result set; we use TABLE return)
 *
 * NOTE: Teradata macros can return multiple result sets. In Snowflake,
 * this is split into two separate procedures or combined into one
 * with a CHECK_TYPE discriminator column.
 **********************************************************************/

-- Combined version: returns both check types in a single result set
CREATE OR REPLACE PROCEDURE BANKING_DW.DAILY_BALANCE_CHECK(
    P_CHECK_DATE DATE
)
RETURNS TABLE (
    CHECK_TYPE VARCHAR(30),
    ACCOUNT_ID_OR_TYPE VARCHAR(20),
    DETAIL_1 VARCHAR(100),
    DETAIL_2 VARCHAR(20),
    METRIC_1 NUMBER(18,2),
    METRIC_2 NUMBER(18,2),
    METRIC_3 NUMBER(18,2),
    METRIC_4 NUMBER(18,2),
    COUNT_VALUE INTEGER
)
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    res RESULTSET;
BEGIN
    res := (
        -- Summary of all account balances as of the check date
        SELECT
            'BALANCE_SUMMARY' AS CHECK_TYPE,
            a.ACCOUNT_TYPE AS ACCOUNT_ID_OR_TYPE,
            a.CURRENCY_CODE AS DETAIL_1,
            NULL AS DETAIL_2,
            SUM(ft.RUNNING_BALANCE) AS METRIC_1,
            AVG(ft.RUNNING_BALANCE) AS METRIC_2,
            MIN(ft.RUNNING_BALANCE) AS METRIC_3,
            MAX(ft.RUNNING_BALANCE) AS METRIC_4,
            COUNT(*) AS COUNT_VALUE
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
            a.ACCOUNT_ID AS ACCOUNT_ID_OR_TYPE,
            c.FIRST_NAME || ' ' || c.LAST_NAME AS DETAIL_1,
            a.ACCOUNT_TYPE AS DETAIL_2,
            ft.RUNNING_BALANCE AS METRIC_1,
            a.OVERDRAFT_LIMIT AS METRIC_2,
            ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT AS METRIC_3,
            NULL AS METRIC_4,
            NULL AS COUNT_VALUE
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
        ORDER BY METRIC_1 ASC
    );
    RETURN TABLE(res);
END;
$$;
