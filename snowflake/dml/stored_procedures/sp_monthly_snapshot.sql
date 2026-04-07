/**********************************************************************
 * SP_MONTHLY_SNAPSHOT (Snowflake)
 *
 * Calculates month-end account snapshots from transaction data.
 * Converted from Teradata stored procedure.
 *
 * Changes:
 *   - REPLACE PROCEDURE -> CREATE OR REPLACE PROCEDURE
 *   - Teradata SQL procedure -> Snowflake Scripting (SQL)
 *   - VOLATILE TABLE -> CREATE TEMPORARY TABLE
 *   - SEL -> SELECT
 *   - ACTIVITY_COUNT -> SQLROWCOUNT
 *   - FORMAT on expressions -> TO_CHAR()
 *   - CAST(... AS DATE FORMAT ...) -> DATE_FROM_PARTS() / TO_DATE()
 *   - ON COMMIT PRESERVE ROWS -> default in Snowflake temp tables
 *   - PRIMARY INDEX -> removed (no PI in Snowflake)
 *   - Teradata type casting (SMALLINT) -> explicit ::SMALLINT
 *   - COLLECT STATISTICS -> removed
 *   - OUT parameters -> OBJECT return value
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_MONTHLY_SNAPSHOT(
    P_SNAPSHOT_YEAR   INTEGER,
    P_SNAPSHOT_MONTH  INTEGER,
    P_BATCH_ID        BIGINT
)
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    v_snapshot_date DATE;
    v_period_start DATE;
    v_period_end DATE;
    v_prev_snapshot_date DATE;
    v_snapshot_month_key INTEGER;
    v_rows_merged INTEGER DEFAULT 0;
    v_return_code INTEGER DEFAULT 0;
    v_result OBJECT;
BEGIN
    -- Calculate period boundaries
    v_period_start := DATE_FROM_PARTS(:P_SNAPSHOT_YEAR, :P_SNAPSHOT_MONTH, 1);
    v_period_end := DATEADD('day', -1, DATEADD('month', 1, :v_period_start));
    v_snapshot_date := :v_period_end;
    v_snapshot_month_key := (:P_SNAPSHOT_YEAR * 100) + :P_SNAPSHOT_MONTH;
    v_prev_snapshot_date := DATEADD('day', -1, :v_period_start);

    -- Create temporary table for aggregated transaction data
    CREATE OR REPLACE TEMPORARY TABLE VT_TXN_AGGREGATES AS
    SELECT
        ft.ACCOUNT_KEY,
        SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('DEBIT', 'FEE')
                 THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS TOTAL_DEBITS,
        SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('CREDIT', 'INTEREST')
                 THEN ft.TRANSACTION_AMOUNT ELSE 0 END) AS TOTAL_CREDITS,
        SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('DEBIT', 'FEE') THEN 1 ELSE 0 END) AS DEBIT_COUNT,
        SUM(CASE WHEN ft.TRANSACTION_TYPE IN ('CREDIT', 'INTEREST') THEN 1 ELSE 0 END) AS CREDIT_COUNT,
        SUM(CASE WHEN ft.TRANSACTION_TYPE = 'INTEREST' AND ft.TRANSACTION_AMOUNT > 0
                 THEN ft.TRANSACTION_AMOUNT ELSE 0 END) AS INTEREST_EARNED,
        SUM(CASE WHEN ft.TRANSACTION_TYPE = 'INTEREST' AND ft.TRANSACTION_AMOUNT < 0
                 THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS INTEREST_CHARGED,
        SUM(CASE WHEN ft.TRANSACTION_TYPE = 'FEE'
                 THEN ABS(ft.TRANSACTION_AMOUNT) ELSE 0 END) AS FEES_CHARGED,
        MIN(ft.RUNNING_BALANCE) AS MIN_BALANCE,
        MAX(ft.RUNNING_BALANCE) AS MAX_BALANCE,
        AVG(ft.RUNNING_BALANCE) AS AVG_BALANCE,
        SUM(CASE WHEN ft.RUNNING_BALANCE < 0 THEN 1 ELSE 0 END) AS OVERDRAFT_DAYS
    FROM BANKING_DW.FACT_TRANSACTION ft
    WHERE ft.TRANSACTION_DATE BETWEEN :v_period_start AND :v_period_end
    GROUP BY ft.ACCOUNT_KEY;

    -- Merge into snapshot table
    MERGE INTO BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT tgt
    USING (
        SELECT
            :v_snapshot_date AS SNAPSHOT_DATE,
            :v_snapshot_month_key AS SNAPSHOT_MONTH_KEY,
            a.ACCOUNT_KEY,
            a.CUSTOMER_KEY,
            a.PRODUCT_ID,
            a.BRANCH_ID,
            ZEROIFNULL(prev.CLOSING_BALANCE) AS OPENING_BALANCE,
            ZEROIFNULL(prev.CLOSING_BALANCE)
                + ZEROIFNULL(agg.TOTAL_CREDITS)
                - ZEROIFNULL(agg.TOTAL_DEBITS) AS CLOSING_BALANCE,
            ZEROIFNULL(agg.AVG_BALANCE) AS AVERAGE_BALANCE,
            ZEROIFNULL(agg.MIN_BALANCE) AS MINIMUM_BALANCE,
            ZEROIFNULL(agg.MAX_BALANCE) AS MAXIMUM_BALANCE,
            ZEROIFNULL(agg.TOTAL_DEBITS) AS TOTAL_DEBITS,
            ZEROIFNULL(agg.TOTAL_CREDITS) AS TOTAL_CREDITS,
            ZEROIFNULL(agg.DEBIT_COUNT) AS DEBIT_COUNT,
            ZEROIFNULL(agg.CREDIT_COUNT) AS CREDIT_COUNT,
            ZEROIFNULL(agg.INTEREST_EARNED) AS INTEREST_EARNED,
            ZEROIFNULL(agg.INTEREST_CHARGED) AS INTEREST_CHARGED,
            ZEROIFNULL(agg.FEES_CHARGED) AS FEES_CHARGED,
            ZEROIFNULL(agg.OVERDRAFT_DAYS)::SMALLINT AS DAYS_IN_OVERDRAFT,
            CASE WHEN agg.ACCOUNT_KEY IS NULL
                 THEN DATEDIFF('day', :v_period_start, :v_period_end) + 1
                 ELSE 0
            END::SMALLINT AS DAYS_DORMANT,
            a.CURRENCY_CODE,
            :P_BATCH_ID AS ETL_BATCH_ID
        FROM BANKING_DW.DIM_ACCOUNT a
        LEFT JOIN BANKING_DW.DIM_CUSTOMER c
            ON a.CUSTOMER_ID = c.CUSTOMER_ID
           AND c.CURRENT_FLAG = 'Y'
        LEFT JOIN VT_TXN_AGGREGATES agg
            ON a.ACCOUNT_KEY = agg.ACCOUNT_KEY
        LEFT JOIN BANKING_DW.FACT_MONTHLY_ACCOUNT_SNAPSHOT prev
            ON a.ACCOUNT_KEY = prev.ACCOUNT_KEY
           AND prev.SNAPSHOT_DATE = :v_prev_snapshot_date
        WHERE a.CURRENT_FLAG = 'Y'
          AND a.ACCOUNT_STATUS IN ('ACTIVE', 'DORMANT')
    ) src
    ON tgt.ACCOUNT_KEY = src.ACCOUNT_KEY
       AND tgt.SNAPSHOT_MONTH_KEY = src.SNAPSHOT_MONTH_KEY
    WHEN MATCHED THEN UPDATE SET
        OPENING_BALANCE = src.OPENING_BALANCE,
        CLOSING_BALANCE = src.CLOSING_BALANCE,
        AVERAGE_BALANCE = src.AVERAGE_BALANCE,
        MINIMUM_BALANCE = src.MINIMUM_BALANCE,
        MAXIMUM_BALANCE = src.MAXIMUM_BALANCE,
        TOTAL_DEBITS = src.TOTAL_DEBITS,
        TOTAL_CREDITS = src.TOTAL_CREDITS,
        DEBIT_COUNT = src.DEBIT_COUNT,
        CREDIT_COUNT = src.CREDIT_COUNT,
        INTEREST_EARNED = src.INTEREST_EARNED,
        INTEREST_CHARGED = src.INTEREST_CHARGED,
        FEES_CHARGED = src.FEES_CHARGED,
        DAYS_IN_OVERDRAFT = src.DAYS_IN_OVERDRAFT,
        DAYS_DORMANT = src.DAYS_DORMANT,
        ETL_BATCH_ID = src.ETL_BATCH_ID,
        ETL_INSERT_TS = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
        SNAPSHOT_DATE, SNAPSHOT_MONTH_KEY, ACCOUNT_KEY, CUSTOMER_KEY,
        PRODUCT_ID, BRANCH_ID, OPENING_BALANCE, CLOSING_BALANCE,
        AVERAGE_BALANCE, MINIMUM_BALANCE, MAXIMUM_BALANCE,
        TOTAL_DEBITS, TOTAL_CREDITS, DEBIT_COUNT, CREDIT_COUNT,
        INTEREST_EARNED, INTEREST_CHARGED, FEES_CHARGED,
        DAYS_IN_OVERDRAFT, DAYS_DORMANT, CURRENCY_CODE,
        ETL_BATCH_ID, ETL_INSERT_TS
    ) VALUES (
        src.SNAPSHOT_DATE, src.SNAPSHOT_MONTH_KEY, src.ACCOUNT_KEY, src.CUSTOMER_KEY,
        src.PRODUCT_ID, src.BRANCH_ID, src.OPENING_BALANCE, src.CLOSING_BALANCE,
        src.AVERAGE_BALANCE, src.MINIMUM_BALANCE, src.MAXIMUM_BALANCE,
        src.TOTAL_DEBITS, src.TOTAL_CREDITS, src.DEBIT_COUNT, src.CREDIT_COUNT,
        src.INTEREST_EARNED, src.INTEREST_CHARGED, src.FEES_CHARGED,
        src.DAYS_IN_OVERDRAFT, src.DAYS_DORMANT, src.CURRENCY_CODE,
        src.ETL_BATCH_ID, CURRENT_TIMESTAMP()
    );

    v_rows_merged := SQLROWCOUNT;

    -- Clean up temporary table
    DROP TABLE IF EXISTS VT_TXN_AGGREGATES;

    -- Note: COLLECT STATISTICS removed; Snowflake manages statistics automatically

    v_result := OBJECT_CONSTRUCT(
        'rows_merged', :v_rows_merged,
        'return_code', :v_return_code
    );
    RETURN v_result;
END;
$$;
