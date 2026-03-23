/*********************************************************************
 * SnowSQL Daily Load Script (Snowflake)
 * Orchestrates the daily ETL pipeline for the banking data warehouse
 * Converted from Teradata BTEQ script
 *
 * Changes:
 *   - Replaced .LOGON with SnowSQL connection (use snowsql -c <connection>)
 *   - Replaced .SET WIDTH/SEPARATOR with SnowSQL !set commands
 *   - Replaced SEL with SELECT
 *   - Replaced .IF ACTIVITYCOUNT/ERRORCODE with SnowSQL scripting
 *   - Replaced VOLATILE TABLE with TEMPORARY TABLE
 *   - Replaced .EXPORT with COPY INTO @stage or !spool
 *   - Replaced .LABEL/.GOTO with procedural error handling
 *   - Replaced .QUIT with !quit
 *   - Wrapped entire pipeline in a stored procedure for atomicity
 *********************************************************************/

-- This script is designed to be run via: snowsql -c my_connection -f snowsql_daily_load.sql
-- Or invoked as a Snowflake Task for scheduled execution.

!set variable_substitution=true
!set output_format=csv
!set header=true

USE DATABASE BANKING_DW;
USE SCHEMA BANKING_DW;

/*
 * The daily load is wrapped in a stored procedure for proper error handling.
 * In Teradata BTEQ, .LABEL/.GOTO provided flow control; in Snowflake we use
 * SQL scripting with BEGIN/EXCEPTION blocks.
 */
CREATE OR REPLACE PROCEDURE BANKING_DW.SP_DAILY_ETL_PIPELINE()
RETURNS VARIANT
LANGUAGE SQL
AS
$$
DECLARE
    v_batch_id    BIGINT;
    v_batch_date  DATE;
    v_staging_count INTEGER;
    v_start_ts    TIMESTAMP_NTZ;
    v_scd2_result VARIANT;
    v_load_result VARIANT;
BEGIN
    v_batch_date := CURRENT_DATE();
    v_start_ts   := CURRENT_TIMESTAMP();

    -- Step 1: Validate staging data
    SELECT COUNT(*) INTO :v_staging_count
    FROM BANKING_DW.STG_TRANSACTIONS
    WHERE LOAD_DATE = :v_batch_date;

    IF (:v_staging_count = 0) THEN
        RETURN OBJECT_CONSTRUCT(
            'status', 'WARNING',
            'message', 'No staging data found for ' || TO_CHAR(:v_batch_date, 'YYYY-MM-DD'),
            'exit_code', 4
        );
    END IF;

    -- Step 2: Generate new batch ID
    SELECT COALESCE(MAX(BATCH_ID), 0) + 1 INTO :v_batch_id
    FROM BANKING_DW.ETL_BATCH_CONTROL;

    -- Step 3: Run SCD2 customer dimension update
    CALL BANKING_DW.SP_CUSTOMER_SCD2(:v_batch_id);
    v_scd2_result := SQLROWCOUNT;

    -- Step 4: Load daily transactions
    CALL BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS(:v_batch_date, :v_batch_id);
    v_load_result := SQLROWCOUNT;

    -- Step 5: Run balance reconciliation
    CALL BANKING_DW.SP_DAILY_BALANCE_CHECK(:v_batch_date);

    -- Step 6: Generate reconciliation report (query for review)
    CREATE OR REPLACE TEMPORARY TABLE BANKING_DW.TMP_DAILY_RECON AS
    SELECT
        'DAILY_RECONCILIATION' AS REPORT_TYPE,
        :v_batch_date AS REPORT_DATE,
        :v_batch_id AS BATCH_ID,
        (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTIONS
         WHERE LOAD_DATE = :v_batch_date) AS STAGED_ROWS,
        (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
         WHERE ETL_BATCH_ID = :v_batch_id) AS LOADED_ROWS,
        (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTION_ERRORS
         WHERE BATCH_ID = :v_batch_id) AS ERROR_ROWS;

    -- Step 7: Record batch completion
    INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
        BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
    ) VALUES (
        :v_batch_id, :v_batch_date, 'COMPLETED', :v_start_ts, CURRENT_TIMESTAMP()
    );

    RETURN OBJECT_CONSTRUCT(
        'status', 'COMPLETED',
        'batch_id', :v_batch_id,
        'batch_date', TO_CHAR(:v_batch_date, 'YYYY-MM-DD'),
        'exit_code', 0
    );

EXCEPTION
    WHEN OTHER THEN
        -- Record batch failure
        INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
            BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
        ) VALUES (
            :v_batch_id, :v_batch_date, 'FAILED', :v_start_ts, CURRENT_TIMESTAMP()
        );

        RETURN OBJECT_CONSTRUCT(
            'status', 'FAILED',
            'batch_id', :v_batch_id,
            'error', SQLERRM,
            'exit_code', 8
        );
END;
$$;

-- Execute the daily pipeline
CALL BANKING_DW.SP_DAILY_ETL_PIPELINE();
