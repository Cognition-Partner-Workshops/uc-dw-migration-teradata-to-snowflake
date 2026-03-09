/**********************************************************************
 * SNOWSQL_DAILY_LOAD -- Daily ETL Pipeline (Snowflake)
 * Converted from Teradata BTEQ script bteq_daily_load.btq
 *
 * Conversion notes:
 * - Removed: .LOGON (use SnowSQL connection config or --connection flag)
 * - Removed: .SET WIDTH/SEPARATOR (use SnowSQL output format settings)
 * - Replaced: .IF ACTIVITYCOUNT / .IF ERRORCODE -> procedural control flow
 * - Replaced: .GOTO / .LABEL -> IF/ELSE blocks
 * - Replaced: .EXPORT REPORT FILE= -> COPY INTO @stage
 * - Replaced: CREATE VOLATILE TABLE -> CREATE TEMPORARY TABLE
 * - Replaced: EXEC macro -> CALL procedure
 * - Replaced: SEL -> SELECT
 * - Replaced: .QUIT N -> RETURN with status message
 *
 * Best approach: Converted to a single Snowflake stored procedure that
 * encapsulates the pipeline, making it self-contained and schedulable
 * via Snowflake Tasks.
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_DAILY_LOAD_PIPELINE()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_batch_id BIGINT;
    v_batch_start_ts TIMESTAMP_NTZ(0);
    v_staging_count INTEGER;
    v_new_rows INTEGER;
    v_changed_rows INTEGER;
    v_scd2_result VARCHAR;
    v_txn_result VARCHAR;
BEGIN
    v_batch_start_ts := CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0);

    -- ================================================================
    -- Step 1: Validate staging data
    -- ================================================================
    SELECT COUNT(*)
    INTO :v_staging_count
    FROM BANKING_DW.STG_TRANSACTIONS
    WHERE LOAD_DATE = CURRENT_DATE();

    IF (:v_staging_count = 0) THEN
        RETURN 'WARNING: No staging data found for ' || TO_CHAR(CURRENT_DATE(), 'YYYY-MM-DD');
    END IF;

    -- ================================================================
    -- Step 2: Generate new batch ID
    -- ================================================================
    BEGIN
        SELECT COALESCE(MAX(BATCH_ID), 0) + 1
        INTO :v_batch_id
        FROM BANKING_DW.ETL_BATCH_CONTROL;
    EXCEPTION
        WHEN OTHER THEN
            RETURN 'ERROR: Failed to generate batch ID. ' || SQLERRM;
    END;

    -- ================================================================
    -- Step 3: Run SCD2 customer dimension update
    -- ================================================================
    BEGIN
        CALL BANKING_DW.SP_CUSTOMER_SCD2(
            :v_batch_id, 0, 0, 0
        );
    EXCEPTION
        WHEN OTHER THEN
            -- Record failure in batch control
            INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
                BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
            ) VALUES (
                :v_batch_id, CURRENT_DATE(), 'FAILED',
                :v_batch_start_ts, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
            );
            RETURN 'ERROR: SCD2 failed. ' || SQLERRM;
    END;

    -- ================================================================
    -- Step 4: Load daily transactions
    -- ================================================================
    BEGIN
        CALL BANKING_DW.SP_LOAD_DAILY_TRANSACTIONS(
            CURRENT_DATE(),
            :v_batch_id
        );
    EXCEPTION
        WHEN OTHER THEN
            INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
                BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
            ) VALUES (
                :v_batch_id, CURRENT_DATE(), 'FAILED',
                :v_batch_start_ts, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
            );
            RETURN 'ERROR: Transaction load failed. ' || SQLERRM;
    END;

    -- ================================================================
    -- Step 5: Run balance reconciliation
    -- ================================================================
    CALL BANKING_DW.SP_DAILY_BALANCE_CHECK(CURRENT_DATE());

    -- ================================================================
    -- Step 6: Export reconciliation report to stage
    -- ================================================================
    COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/daily_recon/daily_recon_
        FROM (
            SELECT
                'DAILY_RECONCILIATION' AS REPORT_TYPE,
                TO_CHAR(CURRENT_DATE(), 'YYYY-MM-DD') AS REPORT_DATE,
                :v_batch_id AS BATCH_ID,
                (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTIONS
                 WHERE LOAD_DATE = CURRENT_DATE()) AS STAGED_ROWS,
                (SELECT COUNT(*) FROM BANKING_DW.FACT_TRANSACTION
                 WHERE ETL_BATCH_ID = :v_batch_id) AS LOADED_ROWS,
                (SELECT COUNT(*) FROM BANKING_DW.STG_TRANSACTION_ERRORS
                 WHERE BATCH_ID = :v_batch_id) AS ERROR_ROWS
        )
        FILE_FORMAT = (TYPE = 'CSV' HEADER = TRUE)
        OVERWRITE = TRUE
        SINGLE = TRUE;

    -- ================================================================
    -- Step 7: Record batch completion
    -- ================================================================
    INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
        BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
    ) VALUES (
        :v_batch_id, CURRENT_DATE(), 'COMPLETED',
        :v_batch_start_ts, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
    );

    RETURN 'SUCCESS: Daily load completed. Batch ID: ' || TO_CHAR(:v_batch_id);

EXCEPTION
    WHEN OTHER THEN
        -- Record failure
        INSERT INTO BANKING_DW.ETL_BATCH_CONTROL (
            BATCH_ID, BATCH_DATE, BATCH_STATUS, START_TS, END_TS
        ) VALUES (
            :v_batch_id, CURRENT_DATE(), 'FAILED',
            :v_batch_start_ts, CURRENT_TIMESTAMP()::TIMESTAMP_NTZ(0)
        );
        RETURN 'ERROR: Pipeline failed. ' || SQLERRM;
END;
$$;

-- ================================================================
-- Optional: Schedule as a Snowflake Task (replaces BTEQ cron scheduling)
-- ================================================================
-- CREATE OR REPLACE TASK BANKING_DW.TASK_DAILY_LOAD
--     WAREHOUSE = 'ETL_WH'
--     SCHEDULE = 'USING CRON 0 6 * * * Europe/Oslo'  -- 06:00 Oslo time daily
--     COMMENT = 'Daily ETL pipeline: SCD2 + transaction load + reconciliation'
-- AS
--     CALL BANKING_DW.SP_DAILY_LOAD_PIPELINE();
--
-- ALTER TASK BANKING_DW.TASK_DAILY_LOAD RESUME;
