/**********************************************************************
 * Daily Load Script (Snowflake / SnowSQL)
 *
 * Converted from Teradata BTEQ script: bteq_daily_load.btq
 *
 * Changes:
 *   - .LOGON -> SnowSQL connection profile
 *   - .SET -> SnowSQL !set
 *   - VOLATILE TABLE -> TEMPORARY TABLE
 *   - SEL -> SELECT
 *   - (FORMAT '...') -> TO_CHAR()
 *   - .IF ACTIVITYCOUNT -> Snowflake Scripting conditional
 *   - .IF ERRORCODE -> TRY/CATCH or EXCEPTION handling
 *   - .EXPORT REPORT FILE= -> COPY INTO @stage
 *   - .LABEL / .GOTO -> procedural block control flow
 *   - EXEC macro -> CALL procedure
 *   - .QUIT with return codes -> procedural RETURN
 *
 * This script is best run as a Snowflake stored procedure for
 * proper error handling and flow control. Alternatively, use
 * Snowflake Tasks for scheduled orchestration.
 *
 * Usage:
 *   CALL BANKING_DW.SP_DAILY_ETL_PIPELINE();
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_DAILY_ETL_PIPELINE()
RETURNS OBJECT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    v_batch_id BIGINT;
    v_batch_start_ts TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    v_staging_count INTEGER;
    v_scd2_result OBJECT;
    v_txn_result OBJECT;
    v_recon_result OBJECT;
    v_result OBJECT;
BEGIN
    -- ================================================================
    -- Step 1: Validate staging data
    -- ================================================================
    SELECT COUNT(*) INTO :v_staging_count
    FROM BANKING_DW.STG_TRANSACTIONS
    WHERE LOAD_DATE = CURRENT_DATE;

    IF (v_staging_count = 0) THEN
        v_result := OBJECT_CONSTRUCT(
            'status', 'WARNING',
            'message', 'No staging data found for ' || TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD')
        );
        RETURN v_result;
    END IF;

    -- ================================================================
    -- Step 2: Generate new batch ID
    -- ================================================================
    SELECT COALESCE(MAX(BATCH_ID), 0) + 1 INTO :v_batch_id
    FROM BANKING_DW.ETL_BATCH_CONTROL;

    -- ================================================================
    -- Step 3: Run SCD2 customer dimension update
    -- ================================================================
    CALL BANKING_DW.SP_CUSTOMER_SCD2(:v_batch_id);
    -- Result is captured via LAST_QUERY_ID if needed

    -- ================================================================
    -- Step 4: Load daily transactions
    -- ================================================================
    CALL BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS(CURRENT_DATE, :v_batch_id);

    -- ================================================================
    -- Step 5: Run balance reconciliation
    -- ================================================================
    CALL BANKING_DW.DAILY_BALANCE_CHECK(CURRENT_DATE);

    -- ================================================================
    -- Step 6: Export reconciliation report to stage
    -- ================================================================
    COPY INTO @BANKING_DW.EXPORT_STAGE/daily_recon_
    FROM (
        SELECT
            'DAILY_RECONCILIATION' AS REPORT_TYPE,
            TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD') AS REPORT_DATE,
            :v_batch_id AS BATCH_ID,
            (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTIONS
             WHERE LOAD_DATE = CURRENT_DATE) AS STAGED_ROWS,
            (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
             WHERE ETL_BATCH_ID = :v_batch_id) AS LOADED_ROWS,
            (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTION_ERRORS
             WHERE BATCH_ID = :v_batch_id) AS ERROR_ROWS
    )
    FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE)
    HEADER = TRUE
    OVERWRITE = TRUE
    SINGLE = TRUE;

    -- ================================================================
    -- Step 7: Record batch completion
    -- ================================================================
    INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
        BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
    ) VALUES (
        :v_batch_id, CURRENT_DATE, 'COMPLETED', :v_batch_start_ts, CURRENT_TIMESTAMP()
    );

    v_result := OBJECT_CONSTRUCT(
        'status', 'COMPLETED',
        'batch_id', :v_batch_id,
        'batch_date', TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD')
    );
    RETURN v_result;

EXCEPTION
    WHEN OTHER THEN
        -- Record batch failure
        INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
            BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
        ) VALUES (
            :v_batch_id, CURRENT_DATE, 'FAILED', :v_batch_start_ts, CURRENT_TIMESTAMP()
        );
        v_result := OBJECT_CONSTRUCT(
            'status', 'FAILED',
            'batch_id', :v_batch_id,
            'error_code', SQLCODE,
            'error_message', SQLERRM
        );
        RETURN v_result;
END;
$$;

-- ================================================================
-- Optional: Create a Snowflake Task for daily scheduling
-- (equivalent to cron-scheduling the BTEQ script)
-- ================================================================
-- CREATE OR REPLACE TASK BANKING_DW.TASK_DAILY_ETL_PIPELINE
--   WAREHOUSE = 'ETL_WH'
--   SCHEDULE = 'USING CRON 0 6 * * * Europe/Oslo'
-- AS
--   CALL BANKING_DW.SP_DAILY_ETL_PIPELINE();
--
-- ALTER TASK BANKING_DW.TASK_DAILY_ETL_PIPELINE RESUME;
