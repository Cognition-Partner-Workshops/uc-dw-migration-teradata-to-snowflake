{{ config(alias='ETL_BATCH_CONTROL') }}

select
    cast(BATCH_ID as NUMBER(19,0)) as BATCH_ID,
    cast(BATCH_DATE as DATE) as BATCH_DATE,
    cast(BATCH_STATUS as VARCHAR(20)) as BATCH_STATUS,
    cast(START_TS as TIMESTAMP_NTZ(0)) as START_TS,
    cast(END_TS as TIMESTAMP_NTZ(0)) as END_TS
from {{ source('td_source', 'ETL_BATCH_CONTROL') }}
union all
select
    cast({{ batch_id() }} as NUMBER(19,0)) as BATCH_ID,
    cast({{ run_day() }} as DATE) as BATCH_DATE,
    cast('COMPLETED' as VARCHAR(20)) as BATCH_STATUS,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as START_TS,
    cast({{ load_timestamp() }} as TIMESTAMP_NTZ(0)) as END_TS
