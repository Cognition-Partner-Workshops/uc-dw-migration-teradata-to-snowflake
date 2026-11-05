select
    ft.transaction_id,
    ft.transaction_date,
    ft.transaction_ts,
    c.customer_id,
    c.first_name,
    c.last_name,
    c.kyc_status,
    a.account_id,
    a.account_type,
    ft.transaction_type,
    ft.transaction_subtype,
    ft.transaction_amount,
    ft.transaction_currency,
    ft.base_currency_amount,
    ft.merchant_name,
    ft.counterparty_acct,
    ft.is_international,
    ft.reference_number,
    ft.description_text,
    b.branch_name,
    b.region,
    case
        when ft.base_currency_amount >= 100000 then 'THRESHOLD_EXCEEDED'
        when ft.is_international = 1 and ft.base_currency_amount >= 25000 then 'INTL_THRESHOLD'
        when ft.is_flagged = 1 then 'FLAGGED_SUSPICIOUS'
        else 'REVIEW'
    end as reporting_category,
    md5(cast(ft.transaction_id as varchar) || '|' || cast(ft.transaction_date as varchar)) as row_hash,
    ft.etl_batch_id
from {{ source('td_core', 'FACT_TRANSACTION') }} ft
inner join {{ source('td_core', 'DIM_ACCOUNT') }} a
    on ft.account_key = a.account_key and a.current_flag = 'Y'
inner join {{ source('td_core', 'DIM_CUSTOMER') }} c
    on ft.customer_key = c.customer_key and c.current_flag = 'Y'
left join {{ source('td_core', 'DIM_BRANCH') }} b on ft.branch_id = b.branch_id
where ft.base_currency_amount >= 100000
    or (ft.is_international = 1 and ft.base_currency_amount >= 25000)
    or ft.is_flagged = 1
qualify row_number() over (
    partition by ft.transaction_id
    order by ft.etl_batch_id desc, ft.transaction_date desc, ft.account_key
) = 1
