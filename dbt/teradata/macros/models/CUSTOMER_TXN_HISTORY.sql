{% set customer_id = var('customer_txn_history_customer_id', 1010) %}
{% set start_date = var('customer_txn_history_start_date', '2026-01-01') %}
{% set end_date = var('customer_txn_history_end_date', '2026-01-31') %}
{% set txn_type = var('customer_txn_history_txn_type', 'ALL') %}

select
    ft.TRANSACTION_DATE as TXN_DATE,
    ft.TRANSACTION_TIME as TXN_TIME,
    a.ACCOUNT_ID,
    a.ACCOUNT_TYPE,
    ft.TRANSACTION_TYPE,
    ft.TRANSACTION_SUBTYPE,
    ft.CHANNEL,
    ft.TRANSACTION_AMOUNT as AMOUNT,
    ft.TRANSACTION_CURRENCY as CCY,
    ft.RUNNING_BALANCE as BALANCE,
    coalesce(ft.MERCHANT_NAME, ft.COUNTERPARTY_ACCT, '--') as PAYEE,
    ft.DESCRIPTION_TEXT as DESCRIPTION,
    ft.REFERENCE_NUMBER as REF_NO
from {{ source('td_core', 'FACT_TRANSACTION') }} ft
join {{ source('td_core', 'DIM_ACCOUNT') }} a
  on ft.ACCOUNT_KEY = a.ACCOUNT_KEY and a.CURRENT_FLAG = 'Y'
join {{ source('td_core', 'DIM_CUSTOMER') }} c
  on ft.CUSTOMER_KEY = c.CUSTOMER_KEY and c.CURRENT_FLAG = 'Y'
where c.CUSTOMER_ID = {{ customer_id }}
  and ft.TRANSACTION_DATE between cast('{{ start_date }}' as date) and cast('{{ end_date }}' as date)
  and (ft.TRANSACTION_TYPE = '{{ txn_type }}' or '{{ txn_type }}' = 'ALL')
order by ft.TRANSACTION_DATE desc, ft.TRANSACTION_TIME desc
limit 1000
