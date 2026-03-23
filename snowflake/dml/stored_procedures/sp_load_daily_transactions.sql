/**********************************************************************
 * SP_LOAD_DAILY_TRANSACTIONS (Snowflake)
 * Loads daily transaction data from staging to fact table
 * Converted from Teradata stored procedure
 * Changes:
 *   - Replaced REPLACE PROCEDURE with CREATE OR REPLACE PROCEDURE
 *   - Converted to Snowflake SQL scripting
 *   - Replaced ACTIVITY_COUNT with SQLROWCOUNT
 *   - Replaced SEL with SELECT
 *   - Replaced Teradata date/time arithmetic with Snowflake functions
 *   - Replaced FORMAT casts with TO_CHAR
 *   - Replaced SQLCODE with SQLERRM / SQLCODE in exception handler
 *   - Removed COLLECT STATISTICS
 *   - ZEROIFNULL kept (natively supported)
 *   - Adjusted TIMESTAMP arithmetic to Snowflake syntax
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS(
    P_BATCH_DATE DATE,
    P_BATCH_ID   BIGINT
)
RETURNS VARIANT
LANGUAGE SQL
AS
$$
DECLARE
    v_error_count    INTEGER DEFAULT 0;
    v_rows_inserted  INTEGER DEFAULT 0;
    v_rows_rejected  INTEGER DEFAULT 0;
    v_start_ts       TIMESTAMP_NTZ;
    v_return_code    INTEGER DEFAULT 0;
BEGIN
    v_start_ts := CURRENT_TIMESTAMP();

    -- Log start
    INSERT INTO BANKING_DW.ETL_LOG (
        PROCEDURE_NAME, BATCH_ID, LOG_LEVEL, LOG_MESSAGE, LOG_TS
    ) VALUES (
        'SP_LOAD_DAILY_TRANSACTIONS', :P_BATCH_ID, 'INFO',
        'Started loading transactions for date: ' || TO_CHAR(:P_BATCH_DATE, 'YYYY-MM-DD'),
        :v_start_ts
    );

    -- Reject bad records to error table
    INSERT INTO BANKING_DW.STG_TRANSACTION_ERRORS
    SELECT stg.*, 'INVALID_ACCOUNT' AS ERROR_REASON, :P_BATCH_ID AS BATCH_ID
    FROM BANKING_DW.STG_TRANSACTIONS stg
    WHERE stg.LOAD_DATE = :P_BATCH_DATE
      AND stg.ACCOUNT_ID NOT IN (
          SELECT ACCOUNT_ID FROM BANKING_DW.DIM_ACCOUNT WHERE CURRENT_FLAG = 'Y'
      );

    v_error_count := SQLROWCOUNT;

    -- Insert valid transactions
    INSERT INTO BANKING_DW.FACT_TRANSACTION (
        TRANSACTION_ID, TRANSACTION_DATE, TRANSACTION_TIME, TRANSACTION_TS,
        ACCOUNT_KEY, CUSTOMER_KEY, PRODUCT_ID, BRANCH_ID, DATE_KEY,
        TRANSACTION_TYPE, TRANSACTION_SUBTYPE, CHANNEL,
        TRANSACTION_AMOUNT, TRANSACTION_CURRENCY, BASE_CURRENCY_AMOUNT,
        EXCHANGE_RATE, MERCHANT_ID, MERCHANT_NAME, MERCHANT_CATEGORY,
        COUNTERPARTY_ACCT, REFERENCE_NUMBER, DESCRIPTION_TEXT,
        IS_INTERNATIONAL, POSTING_DATE, VALUE_DATE,
        ETL_BATCH_ID, ETL_INSERT_TS
    )
    SELECT
        stg.TRANSACTION_ID,
        stg.TRANSACTION_DATE,
        stg.TRANSACTION_TIME,
        stg.TRANSACTION_DATE::TIMESTAMP_NTZ + stg.TRANSACTION_TIME::TIME,
        a.ACCOUNT_KEY,
        c.CUSTOMER_KEY,
        a.PRODUCT_ID,
        a.BRANCH_ID,
        TO_NUMBER(TO_CHAR(stg.TRANSACTION_DATE, 'YYYYMMDD')),
        stg.TRANSACTION_TYPE,
        stg.TRANSACTION_SUBTYPE,
        stg.CHANNEL,
        stg.TRANSACTION_AMOUNT,
        stg.CURRENCY_CODE,
        CASE WHEN stg.CURRENCY_CODE <> 'NOK'
             THEN stg.TRANSACTION_AMOUNT * ZEROIFNULL(fx.EXCHANGE_RATE)
             ELSE stg.TRANSACTION_AMOUNT
        END,
        ZEROIFNULL(fx.EXCHANGE_RATE),
        stg.MERCHANT_ID,
        stg.MERCHANT_NAME,
        stg.MERCHANT_CATEGORY,
        stg.COUNTERPARTY_ACCT,
        stg.REFERENCE_NUMBER,
        stg.DESCRIPTION_TEXT,
        CASE WHEN stg.CURRENCY_CODE <> 'NOK' THEN 1 ELSE 0 END,
        stg.POSTING_DATE,
        stg.VALUE_DATE,
        :P_BATCH_ID,
        CURRENT_TIMESTAMP()
    FROM BANKING_DW.STG_TRANSACTIONS stg
    INNER JOIN BANKING_DW.DIM_ACCOUNT a
        ON stg.ACCOUNT_ID = a.ACCOUNT_ID
       AND a.CURRENT_FLAG = 'Y'
    INNER JOIN BANKING_DW.DIM_CUSTOMER c
        ON a.CUSTOMER_ID = c.CUSTOMER_ID
       AND c.CURRENT_FLAG = 'Y'
    LEFT JOIN BANKING_DW.DIM_EXCHANGE_RATES fx
        ON stg.CURRENCY_CODE = fx.FROM_CURRENCY
       AND fx.TO_CURRENCY = 'NOK'
       AND stg.TRANSACTION_DATE = fx.RATE_DATE
    WHERE stg.LOAD_DATE = :P_BATCH_DATE
      AND stg.ACCOUNT_ID IN (
          SELECT ACCOUNT_ID FROM BANKING_DW.DIM_ACCOUNT WHERE CURRENT_FLAG = 'Y'
      );

    v_rows_inserted := SQLROWCOUNT;
    v_rows_rejected := :v_error_count;

    -- Log completion
    INSERT INTO BANKING_DW.ETL_LOG (
        PROCEDURE_NAME, BATCH_ID, LOG_LEVEL, LOG_MESSAGE, LOG_TS
    ) VALUES (
        'SP_LOAD_DAILY_TRANSACTIONS', :P_BATCH_ID, 'INFO',
        'Completed. Inserted: ' || :v_rows_inserted::VARCHAR ||
        ', Rejected: ' || :v_rows_rejected::VARCHAR ||
        ', Duration: ' || DATEDIFF('second', :v_start_ts, CURRENT_TIMESTAMP())::VARCHAR || 's',
        CURRENT_TIMESTAMP()
    );

    RETURN OBJECT_CONSTRUCT(
        'rows_inserted', :v_rows_inserted,
        'rows_rejected', :v_rows_rejected,
        'return_code', 0
    );

EXCEPTION
    WHEN OTHER THEN
        INSERT INTO BANKING_DW.ETL_LOG (
            PROCEDURE_NAME, BATCH_ID, LOG_LEVEL, LOG_MESSAGE, LOG_TS
        ) VALUES (
            'SP_LOAD_DAILY_TRANSACTIONS', :P_BATCH_ID, 'ERROR',
            'Error: ' || SQLERRM || ' at ' || CURRENT_TIMESTAMP()::VARCHAR,
            CURRENT_TIMESTAMP()
        );
        RETURN OBJECT_CONSTRUCT(
            'rows_inserted', :v_rows_inserted,
            'rows_rejected', :v_rows_rejected,
            'return_code', SQLCODE
        );
END;
$$;
