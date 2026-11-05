{% set check_date = var('daily_balance_check_date', '2026-01-31') %}

with latest as (
    select
        a.ACCOUNT_TYPE,
        a.CURRENCY_CODE,
        ft.RUNNING_BALANCE
    from {{ source('td_core', 'DIM_ACCOUNT') }} a
    join {{ source('td_core', 'FACT_TRANSACTION') }} ft on a.ACCOUNT_KEY = ft.ACCOUNT_KEY
    where a.CURRENT_FLAG = 'Y'
      and a.ACCOUNT_STATUS = 'ACTIVE'
      and ft.TRANSACTION_DATE = cast('{{ check_date }}' as date)
    qualify row_number() over (
        partition by ft.ACCOUNT_KEY
        order by ft.TRANSACTION_TS desc, ft.TRANSACTION_ID desc, ft.ETL_BATCH_ID desc
    ) = 1
)
select
    'BALANCE_SUMMARY' as CHECK_TYPE,
    ACCOUNT_TYPE,
    CURRENCY_CODE,
    count(*) as ACCOUNT_COUNT,
    sum(RUNNING_BALANCE) as TOTAL_BALANCE,
    avg(RUNNING_BALANCE) as AVG_BALANCE,
    min(RUNNING_BALANCE) as MIN_BALANCE,
    max(RUNNING_BALANCE) as MAX_BALANCE
from latest
group by ACCOUNT_TYPE, CURRENCY_CODE
