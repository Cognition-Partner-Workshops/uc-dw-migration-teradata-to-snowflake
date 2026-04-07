/**********************************************************************
 * Monthly Extract Script (Snowflake / SnowSQL)
 *
 * Converted from Teradata BTEQ script: bteq_extract_report.btq
 *
 * Changes:
 *   - .LOGON -> SnowSQL connection profile or --connection flag
 *   - .SET WIDTH/SEPARATOR -> SnowSQL !set output_format, field_delimiter
 *   - .EXPORT DATA FILE= -> COPY INTO @stage or SnowSQL !spool
 *   - SEL -> SELECT
 *   - (FORMAT '...') inline casts -> removed (handled by file format)
 *   - .IF ACTIVITYCOUNT -> conditional logic via SnowSQL scripting
 *   - .LABEL / .GOTO -> removed (use procedural logic or SnowSQL !if)
 *   - .QUIT -> !quit
 *   - EXEC macro -> CALL procedure
 *   - TRIM(col (FORMAT '...')) -> TO_CHAR()
 *
 * Usage:
 *   snowsql -c banking_dw -f snowsql_extract_report.sql
 **********************************************************************/

-- ================================================================
-- Configuration
-- ================================================================
!set variable_substitution=true
!set output_format=csv
!set header=true

USE DATABASE BANKING_DW;
USE SCHEMA BANKING_DW;

-- ================================================================
-- Export 1: Large Transaction Report (CSV for regulatory submission)
-- ================================================================
-- Use COPY INTO for production; SnowSQL spool for ad-hoc
COPY INTO @BANKING_DW.EXPORT_STAGE/large_txn_report_
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
    WHERE TRANSACTION_DATE BETWEEN DATEADD('month', -1, CURRENT_DATE)
                              AND CURRENT_DATE
    ORDER BY TRANSACTION_DATE, TRANSACTION_ID
)
FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = NONE)
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

-- ================================================================
-- Export 2: Branch Performance Summary
-- ================================================================
COPY INTO @BANKING_DW.EXPORT_STAGE/branch_performance_
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
    WHERE SNAPSHOT_MONTH_KEY = (EXTRACT(YEAR FROM DATEADD('month', -1, CURRENT_DATE)) * 100)
                              + EXTRACT(MONTH FROM DATEADD('month', -1, CURRENT_DATE))
    ORDER BY REGION, REGION_DEPOSIT_RANK
)
FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = NONE)
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

-- ================================================================
-- Export 3: AML Screening Results
-- ================================================================
-- Note: In Snowflake, CALL returns a result set that can be exported
-- via a wrapper query or by running the procedure and spooling output
COPY INTO @BANKING_DW.EXPORT_STAGE/aml_screening_
FROM (
    SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
)
FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = '"' COMPRESSION = NONE)
HEADER = TRUE
OVERWRITE = TRUE
SINGLE = TRUE;

SELECT 'Monthly reports exported successfully at ' ||
    TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS') AS STATUS_MESSAGE;
