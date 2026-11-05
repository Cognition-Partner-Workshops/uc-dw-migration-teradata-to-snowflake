select
    branch_name as "Branch",
    region as "Region",
    month_label as "Month",
    accounts_serviced as "Accounts",
    total_deposits as "Total Deposits (NOK)",
    total_fees_earned as "Fees Earned",
    region_deposit_rank as "Rank",
    pct_of_region_deposits as "% Region"
from {{ ref('VW_BRANCH_PERFORMANCE') }}
where snapshot_month_key =
    extract(year from cast('{{ var("current_date", "2026-01-31") }}' as date) + interval '-1 month') * 100
    + extract(month from cast('{{ var("current_date", "2026-01-31") }}' as date) + interval '-1 month')
