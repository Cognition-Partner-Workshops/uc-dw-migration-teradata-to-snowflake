{{ config(alias='ETL_LOG') }}

with messages as (
    select 'Started loading transactions for date: ' || to_char({{ run_day() }}, 'YYYY-MM-DD') as message
    union all
    select 'Completed. Inserted: ' || to_varchar((select count(*) from {{ ref('fact_transaction') }} where ETL_BATCH_ID = {{ batch_id() }} and TRANSACTION_ID >= 900000))
        || ', Rejected: ' || to_varchar((select count(*) from {{ ref('stg_transaction_errors') }} where BATCH_ID = {{ batch_id() }})) || ', Duration: 0'
)
select
    cast(PROCEDURE_NAME as VARCHAR(128)) as PROCEDURE_NAME,
    cast(BATCH_ID as NUMBER(19,0)) as BATCH_ID,
    cast(LOG_LEVEL as VARCHAR(10)) as LOG_LEVEL,
    cast(LOG_MESSAGE as VARCHAR(2000)) as LOG_MESSAGE,
    cast(LOG_TS as TIMESTAMP_NTZ(0)) as LOG_TS
from {{ source('td_source', 'ETL_LOG') }}
union all
select
    cast('SP_LOAD_DAILY_TRANSACTIONS' as VARCHAR(128)) as PROCEDURE_NAME,
    cast({{ batch_id() }} as NUMBER(19,0)) as BATCH_ID,
    cast('INFO' as VARCHAR(10)) as LOG_LEVEL,
    cast(message as VARCHAR(2000)) as LOG_MESSAGE,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as LOG_TS
from messages
