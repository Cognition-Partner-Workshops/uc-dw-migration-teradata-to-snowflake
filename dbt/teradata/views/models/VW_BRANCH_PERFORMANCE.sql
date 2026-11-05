with monthly_branch as (
    select
        b.branch_id,
        b.branch_name,
        b.branch_type,
        b.region,
        b.city,
        snap.snapshot_month_key,
        d.month_name || ' ' || cast(d.calendar_year as varchar) as month_label,
        count(distinct snap.account_key) as accounts_serviced,
        count(distinct snap.customer_key) as customers_serviced,
        sum(snap.closing_balance) as total_deposits,
        sum(snap.total_debits + snap.total_credits) as total_volume,
        sum(snap.fees_charged) as total_fees_earned,
        sum(snap.interest_charged) as total_interest_income,
        avg(snap.closing_balance) as avg_account_balance
    from {{ source('td_core', 'FACT_MONTHLY_ACCOUNT_SNAPSHOT') }} snap
    inner join {{ source('td_core', 'DIM_BRANCH') }} b on snap.branch_id = b.branch_id
    inner join {{ source('td_core', 'DIM_DATE') }} d on snap.snapshot_date = d.calendar_date
    where b.is_active = 1
        and snap.snapshot_date >= cast('{{ var("current_date", "2026-01-31") }}' as date) + interval '-24 month'
    group by
        b.branch_id, b.branch_name, b.branch_type, b.region, b.city,
        snap.snapshot_month_key, d.month_name, d.calendar_year
)
select
    branch_id,
    branch_name,
    branch_type,
    region,
    city,
    snapshot_month_key,
    month_label,
    accounts_serviced,
    customers_serviced,
    total_deposits,
    total_volume,
    total_fees_earned,
    total_interest_income,
    avg_account_balance,
    sum(total_fees_earned) over (
        order by snapshot_month_key, branch_id rows unbounded preceding
    ) as cumulative_fees_ytd,
    avg(total_volume) over (
        order by snapshot_month_key, branch_id rows between 2 preceding and current row
    ) as moving_avg_volume_3m,
    rank() over (
        partition by region, snapshot_month_key order by total_deposits desc
    ) as region_deposit_rank,
    total_deposits / nullif(sum(total_deposits) over (
        partition by region, snapshot_month_key
    ), 0) * 100 as pct_of_region_deposits
from monthly_branch
