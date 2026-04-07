/**********************************************************************
 * CUSTOMER_TXN_HISTORY (Snowflake)
 *
 * Retrieves transaction history for a specific customer.
 * Converted from Teradata MACRO to Snowflake stored procedure.
 *
 * Changes:
 *   - REPLACE MACRO -> CREATE OR REPLACE PROCEDURE
 *   - Macro parameters :param -> procedure parameters
 *   - DEFAULT DATE - 30 -> DEFAULT DATEADD('day', -30, CURRENT_DATE)
 *   - SEL -> SELECT
 *   - (FORMAT '...') inline formatting -> removed
 *   - SAMPLE 1000 -> LIMIT 1000 (equivalent row-limiting)
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.CUSTOMER_TXN_HISTORY(
    P_CUST_ID INTEGER,
    P_START_DATE DATE DEFAULT DATEADD('day', -30, CURRENT_DATE),
    P_END_DATE DATE DEFAULT CURRENT_DATE,
    P_TXN_TYPE VARCHAR(20) DEFAULT 'ALL'
)
RETURNS TABLE (
    TXN_DATE DATE,
    TXN_TIME TIME,
    ACCOUNT_ID VARCHAR(20),
    ACCOUNT_TYPE VARCHAR(20),
    TRANSACTION_TYPE VARCHAR(20),
    TRANSACTION_SUBTYPE VARCHAR(30),
    CHANNEL VARCHAR(20),
    AMOUNT DECIMAL(15,2),
    CCY CHAR(3),
    BALANCE DECIMAL(15,2),
    PAYEE VARCHAR(200),
    DESCRIPTION VARCHAR(200),
    REF_NO VARCHAR(30)
)
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    res RESULTSET;
BEGIN
    res := (
        SELECT
            ft.TRANSACTION_DATE AS TXN_DATE,
            ft.TRANSACTION_TIME AS TXN_TIME,
            a.ACCOUNT_ID,
            a.ACCOUNT_TYPE,
            ft.TRANSACTION_TYPE,
            ft.TRANSACTION_SUBTYPE,
            ft.CHANNEL,
            ft.TRANSACTION_AMOUNT AS AMOUNT,
            ft.TRANSACTION_CURRENCY AS CCY,
            ft.RUNNING_BALANCE AS BALANCE,
            COALESCE(ft.MERCHANT_NAME, ft.COUNTERPARTY_ACCT, '--') AS PAYEE,
            ft.DESCRIPTION_TEXT AS DESCRIPTION,
            ft.REFERENCE_NUMBER AS REF_NO
        FROM BANKING_DW.FACT_TRANSACTION ft
        INNER JOIN BANKING_DW.DIM_ACCOUNT a
            ON ft.ACCOUNT_KEY = a.ACCOUNT_KEY AND a.CURRENT_FLAG = 'Y'
        INNER JOIN BANKING_DW.DIM_CUSTOMER c
            ON ft.CUSTOMER_KEY = c.CUSTOMER_KEY AND c.CURRENT_FLAG = 'Y'
        WHERE c.CUSTOMER_ID = :P_CUST_ID
          AND ft.TRANSACTION_DATE BETWEEN :P_START_DATE AND :P_END_DATE
          AND (ft.TRANSACTION_TYPE = :P_TXN_TYPE OR :P_TXN_TYPE = 'ALL')
        ORDER BY ft.TRANSACTION_DATE DESC, ft.TRANSACTION_TIME DESC
        LIMIT 1000
    );
    RETURN TABLE(res);
END;
$$;
