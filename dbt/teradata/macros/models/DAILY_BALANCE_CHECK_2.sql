{% set check_date = var('daily_balance_check_date', '2026-01-31') %}

select
    'NEGATIVE_BALANCE_ALERT' as CHECK_TYPE,
    a.ACCOUNT_ID,
    c.FIRST_NAME || ' ' || c.LAST_NAME as CUSTOMER_NAME,
    a.ACCOUNT_TYPE,
    ft.RUNNING_BALANCE as CURRENT_BALANCE,
    a.OVERDRAFT_LIMIT,
    ft.RUNNING_BALANCE - a.OVERDRAFT_LIMIT as OVER_LIMIT_AMOUNT
from {{ source('td_core', 'DIM_ACCOUNT') }} a
join {{ source('td_core', 'DIM_CUSTOMER') }} c
  on a.CUSTOMER_ID = c.CUSTOMER_ID and c.CURRENT_FLAG = 'Y'
join {{ source('td_core', 'FACT_TRANSACTION') }} ft on a.ACCOUNT_KEY = ft.ACCOUNT_KEY
where a.CURRENT_FLAG = 'Y'
  and a.ACCOUNT_TYPE not in ('CREDIT_CARD', 'LOAN')
  and ft.TRANSACTION_DATE = cast('{{ check_date }}' as date)
  and ft.RUNNING_BALANCE < 0
qualify row_number() over (
    partition by ft.ACCOUNT_KEY
    order by ft.TRANSACTION_TS desc, ft.TRANSACTION_ID desc, ft.ETL_BATCH_ID desc
) = 1
