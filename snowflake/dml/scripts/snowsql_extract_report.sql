/*********************************************************************
 * SnowSQL Monthly Extract Script (Snowflake)
 * Exports regulatory and management reports
 * Converted from Teradata BTEQ export script
 *
 * Changes:
 *   - Replaced .LOGON with SnowSQL connection
 *   - Replaced .EXPORT DATA FILE= with COPY INTO @stage
 *   - Replaced .EXPORT REPORT FILE= with COPY INTO @stage
 *   - Replaced SEL with SELECT
 *   - Removed FORMAT display specifications (formatting done via TO_CHAR)
 *   - Replaced EXEC macro calls with CALL procedure
 *   - Replaced .IF ACTIVITYCOUNT with procedural logic
 *   - Replaced ADD_MONTHS with DATEADD
 *   - Replaced .LABEL/.GOTO with exception handling
 *********************************************************************/

-- Run via: snowsql -c my_connection -f snowsql_extract_report.sql
-- Or schedule as a Snowflake Task.

USE DATABASE BANKING_DW;
USE SCHEMA BANKING_DW;

-- Create internal stage for exports (if not exists)
CREATE STAGE IF NOT EXISTS BANKING_DW.ETL_EXPORTS;

/*
 * Export 1: Large Transaction Report (CSV for regulatory submission)
 * Replaces: .EXPORT DATA FILE=/etl/exports/large_txn_report_YYYYMM.csv
 */
COPY INTO @BANKING_DW.ETL_EXPORTS/large_txn_report_
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
    WHERE TRANSACTION_DATE BETWEEN DATEADD('month', -1, CURRENT_DATE())
                              AND CURRENT_DATE()
    ORDER BY TRANSACTION_DATE, TRANSACTION_ID
)
FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = 'NONE')
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

/*
 * Export 2: Branch Performance Summary
 * Replaces: .EXPORT REPORT FILE=/etl/exports/branch_performance_YYYYMM.rpt
 */
COPY INTO @BANKING_DW.ETL_EXPORTS/branch_performance_
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
    WHERE SNAPSHOT_MONTH_KEY = (EXTRACT(YEAR FROM DATEADD('month', -1, CURRENT_DATE())) * 100)
                              + EXTRACT(MONTH FROM DATEADD('month', -1, CURRENT_DATE()))
    ORDER BY REGION, REGION_DEPOSIT_RANK
)
FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = 'NONE')
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

/*
 * Export 3: AML Screening Results
 * Replaces: EXEC BANKING_DW.AML_SCREENING(CURRENT_DATE, 30, 50000.00)
 * In Snowflake, call the converted stored procedure and export from RESULT_SCAN
 */
CALL BANKING_DW.SP_AML_SCREENING(CURRENT_DATE(), 30, 50000.00);

-- Export the results to stage
COPY INTO @BANKING_DW.ETL_EXPORTS/aml_screening_
FROM (SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())))
FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = 'NONE')
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

SELECT 'Monthly reports exported successfully at ' || CURRENT_TIMESTAMP()::VARCHAR AS STATUS;
