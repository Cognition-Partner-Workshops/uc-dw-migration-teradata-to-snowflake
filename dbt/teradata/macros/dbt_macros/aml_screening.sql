{% macro aml_screening_query(result_set) %}
{% set screening_date = var('aml_screening_date', '2026-01-31') %}
{% set lookback_days = var('aml_lookback_days', 30) %}
{% set amount_threshold = var('aml_amount_threshold', 50000) %}
{% if result_set == 1 %}
select
    'STRUCTURING' as PATTERN_TYPE,
    c.CUSTOMER_ID,
    c.FIRST_NAME || ' ' || c.LAST_NAME as CUSTOMER_NAME,
    c.KYC_STATUS,
    a.ACCOUNT_ID,
    count(*) as TXN_COUNT,
    sum(ft.BASE_CURRENCY_AMOUNT) as TOTAL_AMOUNT,
    avg(ft.BASE_CURRENCY_AMOUNT) as AVG_AMOUNT,
    max(ft.TRANSACTION_DATE) as LAST_TXN_DATE
from {{ source('td_core', 'FACT_TRANSACTION') }} ft
join {{ source('td_core', 'DIM_ACCOUNT') }} a
  on ft.ACCOUNT_KEY = a.ACCOUNT_KEY and a.CURRENT_FLAG = 'Y'
join {{ source('td_core', 'DIM_CUSTOMER') }} c
  on ft.CUSTOMER_KEY = c.CUSTOMER_KEY and c.CURRENT_FLAG = 'Y'
where ft.TRANSACTION_DATE between cast('{{ screening_date }}' as date) - {{ lookback_days }}
                              and cast('{{ screening_date }}' as date)
  and ft.TRANSACTION_TYPE in ('CREDIT', 'DEBIT')
  and ft.BASE_CURRENCY_AMOUNT between {{ amount_threshold }} * 0.8 and {{ amount_threshold }}
group by c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME, c.KYC_STATUS, a.ACCOUNT_ID
having count(*) >= 3
{% elif result_set == 2 %}
with credits as (
    select ACCOUNT_KEY, TRANSACTION_DATE as CREDIT_DATE, BASE_CURRENCY_AMOUNT as CREDIT_AMOUNT
    from {{ source('td_core', 'FACT_TRANSACTION') }}
    where TRANSACTION_TYPE = 'CREDIT'
      and BASE_CURRENCY_AMOUNT >= {{ amount_threshold }}
      and TRANSACTION_DATE between cast('{{ screening_date }}' as date) - {{ lookback_days }}
                                   and cast('{{ screening_date }}' as date)
), debits as (
    select ACCOUNT_KEY, TRANSACTION_DATE as DEBIT_DATE, BASE_CURRENCY_AMOUNT as DEBIT_AMOUNT
    from {{ source('td_core', 'FACT_TRANSACTION') }}
    where TRANSACTION_TYPE in ('DEBIT', 'TRANSFER')
      and BASE_CURRENCY_AMOUNT >= {{ amount_threshold }} * 0.9
      and TRANSACTION_DATE between cast('{{ screening_date }}' as date) - {{ lookback_days }}
                                   and cast('{{ screening_date }}' as date)
)
select
    'RAPID_MOVEMENT' as PATTERN_TYPE,
    c.CUSTOMER_ID,
    c.FIRST_NAME || ' ' || c.LAST_NAME as CUSTOMER_NAME,
    a.ACCOUNT_ID,
    cr.CREDIT_DATE,
    cr.CREDIT_AMOUNT,
    dr.DEBIT_DATE,
    dr.DEBIT_AMOUNT,
    dr.DEBIT_DATE - cr.CREDIT_DATE as DAYS_BETWEEN
from {{ source('td_core', 'DIM_CUSTOMER') }} c
join {{ source('td_core', 'DIM_ACCOUNT') }} a
  on c.CUSTOMER_ID = a.CUSTOMER_ID and a.CURRENT_FLAG = 'Y'
join credits cr on a.ACCOUNT_KEY = cr.ACCOUNT_KEY
join debits dr
  on cr.ACCOUNT_KEY = dr.ACCOUNT_KEY
 and dr.DEBIT_DATE between cr.CREDIT_DATE and cr.CREDIT_DATE + 3
where c.CURRENT_FLAG = 'Y'
{% elif result_set == 3 %}
select
    'NEW_CUSTOMER_INTL' as PATTERN_TYPE,
    c.CUSTOMER_ID,
    c.FIRST_NAME || ' ' || c.LAST_NAME as CUSTOMER_NAME,
    c.ONBOARDING_DATE,
    cast('{{ screening_date }}' as date) - c.ONBOARDING_DATE as DAYS_SINCE_ONBOARD,
    c.KYC_STATUS,
    count(*) as INTL_TXN_COUNT,
    sum(ft.BASE_CURRENCY_AMOUNT) as TOTAL_INTL_AMOUNT
from {{ source('td_core', 'FACT_TRANSACTION') }} ft
join {{ source('td_core', 'DIM_CUSTOMER') }} c
  on ft.CUSTOMER_KEY = c.CUSTOMER_KEY and c.CURRENT_FLAG = 'Y'
where ft.IS_INTERNATIONAL = 1
  and ft.TRANSACTION_DATE between cast('{{ screening_date }}' as date) - {{ lookback_days }}
                                  and cast('{{ screening_date }}' as date)
  and c.ONBOARDING_DATE >= cast('{{ screening_date }}' as date) - 90
group by c.CUSTOMER_ID, c.FIRST_NAME, c.LAST_NAME, c.ONBOARDING_DATE, c.KYC_STATUS
having sum(ft.BASE_CURRENCY_AMOUNT) >= {{ amount_threshold }}
{% else %}
  {{ exceptions.raise_compiler_error('Unknown AML screening result set: ' ~ result_set) }}
{% endif %}
{% endmacro %}
