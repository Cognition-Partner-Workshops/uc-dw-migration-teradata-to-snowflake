{{ config(alias='DIM_EXCHANGE_RATES') }}

select
    cast(FROM_CURRENCY as CHAR(3)) as FROM_CURRENCY,
    cast(TO_CURRENCY as CHAR(3)) as TO_CURRENCY,
    cast(RATE_DATE as DATE) as RATE_DATE,
    cast(EXCHANGE_RATE as DECIMAL(12,6)) as EXCHANGE_RATE
from {{ source('td_source', 'DIM_EXCHANGE_RATES') }}
