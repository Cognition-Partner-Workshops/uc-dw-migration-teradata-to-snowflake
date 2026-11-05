with latest_snapshot as (
    select account_key, closing_balance
    from {{ source('td_core', 'FACT_MONTHLY_ACCOUNT_SNAPSHOT') }}
    qualify row_number() over (
        partition by account_key order by snapshot_date desc
    ) = 1
),
account_summary as (
    select
        a.customer_id,
        count(*) as total_accounts,
        sum(case when a.account_status = 'ACTIVE' then 1 else 0 end) as active_accounts,
        sum(case when a.current_flag = 'Y' then s.closing_balance else 0 end) as total_balance
    from {{ source('td_core', 'DIM_ACCOUNT') }} a
    left join latest_snapshot s on a.account_key = s.account_key
    where a.current_flag = 'Y'
    group by a.customer_id
),
transaction_summary as (
    select
        customer_key,
        count(*) as txn_count_90d,
        sum(abs(transaction_amount)) as txn_amount_90d,
        max(transaction_date) as last_txn_date,
        max(channel) as primary_channel
    from {{ source('td_core', 'FACT_TRANSACTION') }}
    where transaction_date >= cast('{{ var("current_date", "2026-01-31") }}' as date) - 90
    group by customer_key
)
select
    c.customer_id,
    c.first_name || ' ' || c.last_name as full_name,
    c.customer_segment,
    c.risk_score,
    c.credit_rating,
    c.kyc_status,
    c.onboarding_date,
    cast((cast('{{ var("current_date", "2026-01-31") }}' as date) - c.onboarding_date) / 365.25 as decimal(5,1)) as tenure_years,
    coalesce(a.total_accounts, 0) as total_accounts,
    coalesce(a.active_accounts, 0) as active_accounts,
    coalesce(a.total_balance, 0) as total_balance,
    coalesce(t.txn_count_90d, 0) as txn_count_last_90_days,
    coalesce(t.txn_amount_90d, 0) as txn_amount_last_90_days,
    t.last_txn_date,
    t.primary_channel,
    c.city,
    c.country_code
from {{ source('td_core', 'DIM_CUSTOMER') }} c
left join account_summary a on c.customer_id = a.customer_id
left join transaction_summary t on c.customer_key = t.customer_key
where c.current_flag = 'Y' and c.is_active = 1
