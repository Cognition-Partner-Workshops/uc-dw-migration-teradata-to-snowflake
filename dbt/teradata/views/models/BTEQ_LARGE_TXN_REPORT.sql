select
    transaction_id,
    transaction_date,
    customer_id,
    first_name,
    last_name,
    kyc_status,
    account_id,
    account_type,
    transaction_type,
    transaction_amount,
    transaction_currency,
    base_currency_amount,
    is_international,
    reporting_category,
    merchant_name,
    reference_number
from {{ ref('VW_REGULATORY_LARGE_TRANSACTIONS') }}
where transaction_date between
    cast('{{ var("current_date", "2026-01-31") }}' as date) + interval '-1 month'
    and cast('{{ var("current_date", "2026-01-31") }}' as date)
