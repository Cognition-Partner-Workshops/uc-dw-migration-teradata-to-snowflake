WITH counts AS (
    SELECT
        (SELECT count(*) FROM {{ ref('FACT_TRANSACTION') }})
          - (SELECT count(*) FROM {{ source('td_src_core', 'FACT_TRANSACTION') }}) AS inserted,
        (SELECT count(*) FROM {{ ref('STG_TRANSACTION_ERRORS') }})
          - (SELECT count(*) FROM {{ source('td_src_core', 'STG_TRANSACTION_ERRORS') }}) AS rejected
), messages AS (
    SELECT 'Started loading transactions for date: ' || CAST(DATE '{{ var("as_of_date") }}' AS VARCHAR) AS message
    UNION ALL
    SELECT 'Completed. Inserted: ' || inserted || ', Rejected: ' || rejected || ', Duration: 0'
    FROM counts
)
SELECT
    CAST(PROCEDURE_NAME AS VARCHAR(128)) AS PROCEDURE_NAME,
    CAST(BATCH_ID AS BIGINT) AS BATCH_ID,
    CAST(LOG_LEVEL AS VARCHAR(10)) AS LOG_LEVEL,
    CAST(LOG_MESSAGE AS VARCHAR(2000)) AS LOG_MESSAGE,
    CAST(LOG_TS AS TIMESTAMP) AS LOG_TS
FROM {{ source('td_src_core', 'ETL_LOG') }}
UNION ALL
SELECT CAST('SP_LOAD_DAILY_TRANSACTIONS' AS VARCHAR), CAST({{ var("batch_id") }} AS BIGINT),
       CAST('INFO' AS VARCHAR), message, TIMESTAMP '{{ var("load_timestamp") }}'
FROM messages
