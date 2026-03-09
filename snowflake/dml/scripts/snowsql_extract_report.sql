/**********************************************************************
 * SNOWSQL_EXTRACT_REPORT -- Monthly Report Extraction (Snowflake)
 * Converted from Teradata BTEQ script bteq_extract_report.btq
 *
 * Conversion notes:
 * - Removed: .LOGON (use SnowSQL connection config or --connection flag)
 * - Removed: .SET WIDTH/SEPARATOR
 * - Replaced: .EXPORT DATA FILE=path -> COPY INTO @stage FORMAT = (TYPE = 'CSV')
 * - Replaced: .EXPORT REPORT FILE=path -> COPY INTO @stage FORMAT = (TYPE = 'CSV')
 * - Replaced: FORMAT casts in SELECT -> TO_CHAR()
 * - Replaced: EXEC macro -> CALL procedure
 * - Replaced: .LABEL / .GOTO -> procedural IF/ELSE
 * - Replaced: SEL -> SELECT
 *
 * Converted to a Snowflake stored procedure for self-contained execution.
 **********************************************************************/

CREATE OR REPLACE PROCEDURE BANKING_DW.SP_EXTRACT_MONTHLY_REPORTS()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_txn_count INTEGER;
    v_report_month INTEGER;
    v_report_year INTEGER;
BEGIN
    v_report_year := EXTRACT(YEAR FROM ADD_MONTHS(CURRENT_DATE(), -1));
    v_report_month := EXTRACT(MONTH FROM ADD_MONTHS(CURRENT_DATE(), -1));

    -- ================================================================
    -- Export 1: Large Transaction Report (CSV for regulatory submission)
    -- ================================================================
    COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/large_txn_report_
        FROM (
            SELECT
                TRANSACTION_ID,
                TO_CHAR(TRANSACTION_DATE, 'YYYY-MM-DD') AS TRANSACTION_DATE,
                CUSTOMER_ID,
                FIRST_NAME,
                LAST_NAME,
                KYC_STATUS,
                ACCOUNT_ID,
                ACCOUNT_TYPE,
                TRANSACTION_TYPE,
                TO_CHAR(TRANSACTION_AMOUNT, '999,999,999.99') AS TRANSACTION_AMOUNT,
                TRANSACTION_CURRENCY,
                TO_CHAR(BASE_CURRENCY_AMOUNT, '999,999,999.99') AS BASE_CURRENCY_AMOUNT,
                IS_INTERNATIONAL,
                REPORTING_CATEGORY,
                MERCHANT_NAME,
                REFERENCE_NUMBER
            FROM BANKING_DW.VW_REGULATORY_LARGE_TRANSACTIONS
            WHERE TRANSACTION_DATE BETWEEN ADD_MONTHS(CURRENT_DATE(), -1)
                                      AND CURRENT_DATE()
            ORDER BY TRANSACTION_DATE, TRANSACTION_ID
        )
        FILE_FORMAT = (TYPE = 'CSV' HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"')
        OVERWRITE = TRUE
        SINGLE = TRUE;

    v_txn_count := SQLROWCOUNT;

    IF (:v_txn_count = 0) THEN
        RETURN 'WARNING: No large transactions found for the reporting period.';
    END IF;

    -- ================================================================
    -- Export 2: Branch Performance Summary
    -- ================================================================
    COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/branch_performance_
        FROM (
            SELECT
                BRANCH_NAME AS "Branch",
                REGION AS "Region",
                MONTH_LABEL AS "Month",
                ACCOUNTS_SERVICED AS "Accounts",
                TO_CHAR(TOTAL_DEPOSITS, '999,999,999,999.99') AS "Total Deposits (NOK)",
                TO_CHAR(TOTAL_FEES_EARNED, '999,999,999.99') AS "Fees Earned",
                REGION_DEPOSIT_RANK AS "Rank",
                TO_CHAR(PCT_OF_REGION_DEPOSITS, '999.99') AS "% Region"
            FROM BANKING_DW.VW_BRANCH_PERFORMANCE
            WHERE SNAPSHOT_MONTH_KEY = (:v_report_year * 100) + :v_report_month
            ORDER BY REGION, REGION_DEPOSIT_RANK
        )
        FILE_FORMAT = (TYPE = 'CSV' HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"')
        OVERWRITE = TRUE
        SINGLE = TRUE;

    -- ================================================================
    -- Export 3: AML Screening Results
    -- ================================================================
    COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/aml_screening_
        FROM (
            SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
        )
        FILE_FORMAT = (TYPE = 'CSV' HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"')
        OVERWRITE = TRUE
        SINGLE = TRUE;

    -- Run AML screening and export via table function
    -- Note: For the AML export, call the procedure first, then export from a temp table
    CREATE TEMPORARY TABLE IF NOT EXISTS TMP_AML_RESULTS AS
        SELECT * FROM TABLE(
            BANKING_DW.SP_AML_SCREENING(CURRENT_DATE(), 30, 50000.00)
        );

    COPY INTO @BANKING_DW.ETL_EXPORT_STAGE/reports/aml_screening_
        FROM TMP_AML_RESULTS
        FILE_FORMAT = (TYPE = 'CSV' HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"')
        OVERWRITE = TRUE
        SINGLE = TRUE;

    DROP TABLE IF EXISTS TMP_AML_RESULTS;

    RETURN 'SUCCESS: Monthly reports exported at ' ||
           TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS');
END;
$$;

-- ================================================================
-- Optional: Schedule as a Snowflake Task (replaces BTEQ cron scheduling)
-- ================================================================
-- CREATE OR REPLACE TASK BANKING_DW.TASK_MONTHLY_REPORTS
--     WAREHOUSE = 'ETL_WH'
--     SCHEDULE = 'USING CRON 0 8 1 * * Europe/Oslo'  -- 08:00 Oslo time, 1st of each month
--     COMMENT = 'Monthly report extraction: regulatory, branch performance, AML'
-- AS
--     CALL BANKING_DW.SP_EXTRACT_MONTHLY_REPORTS();
--
-- ALTER TASK BANKING_DW.TASK_MONTHLY_REPORTS RESUME;
